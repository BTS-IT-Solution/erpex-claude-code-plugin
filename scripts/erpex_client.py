#!/usr/bin/env python3
"""HTTP client invoked by the erpex-code-agent slash commands and hooks.

Stdlib-only (so the plugin works on a fresh machine without `pip install`).
Reads `~/.config/erpex-code-agent/plugin.toml` for the ERPEX URL, API key,
and the model the rewrite subagent should pin to.

Subcommands map 1:1 to the plugin-mode endpoints in agent_api.py:

    setup --url <u> --api-key <k> --model <m>
    get-task --task <id>
    create-task --project <id> [--name <s>] [--description <s>]
    submit-rewrite --task <id> --file <path>            (file is markdown:
                                                        first H1 = new title,
                                                        rest = BR body)
    submit-plan --task <id> --file <path> [--auto-approve] [--summary <s>]
                  [--claude-session <id>]
    fetch-approved-plan --task <id>                     (prints JSON; exits
                                                        2 with body if 409)
    finish --task <id> --kind rewrite|plan|implement
              --success true|false [--summary <s>] [--error <s>]
    on-exit-plan-mode [--auto-approve]                  (reads JSON hook
                                                        payload from stdin)

`current_task` is resolved in this order: explicit --task arg, then
$CWD/.erpex/current_task, else error. Same for project-id (--project,
$CWD/.erpex/current_project).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Stdlib in 3.11+; fall back to a tiny parser for older interpreters so the
# plugin works on whichever Python ships with the user's OS.
try:
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore


CONFIG_DIR = Path(os.path.expanduser("~/.config/erpex-code-agent"))
CONFIG_PATH = CONFIG_DIR / "plugin.toml"


# ---------------------------------------------------------------- config

def _parse_toml(text: str) -> dict:
    if tomllib is not None:
        return tomllib.loads(text)
    # Minimal fallback: handle the exact shape /erpex-setup writes.
    out: dict = {}
    section = out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            section = out.setdefault(m.group(1), {})
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*=\s*"(.*)"$', line)
        if m:
            section[m.group(1)] = m.group(2)
    return out


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.stderr.write(
            f"erpex-code-agent: not configured. Run /erpex-setup first.\n"
            f"(expected config at {CONFIG_PATH})\n"
        )
        sys.exit(2)
    return _parse_toml(CONFIG_PATH.read_text())


def _save_config(url: str, api_key: str, model: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    body = (
        '[odoo]\n'
        f'url = "{url}"\n'
        f'api_key = "{api_key}"\n'
        '\n'
        '[agent]\n'
        f'model = "{model}"\n'
    )
    CONFIG_PATH.write_text(body)
    try:
        os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows / odd FS — best-effort.


# ---------------------------------------------------------------- HTTP

class HttpError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _request(method: str, path: str, body: dict | None = None) -> dict:
    cfg = _load_config()
    url = cfg["odoo"]["url"].rstrip("/") + path
    headers = {
        "Authorization": "Bearer " + cfg["odoo"]["api_key"],
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        raise HttpError(exc.code, raw) from exc


# ---------------------------------------------------------------- task pointer

def _repo_root() -> Path:
    return Path.cwd()


def _active_task_path() -> Path:
    return _repo_root() / ".erpex" / "current_task"


def _read_active_task() -> int | None:
    p = _active_task_path()
    if not p.exists():
        return None
    txt = p.read_text().strip()
    m = re.search(r"task_id\s*=\s*(\d+)", txt)
    if m:
        return int(m.group(1))
    if txt.isdigit():
        return int(txt)
    return None


def _write_active_task(task_id: int) -> None:
    p = _active_task_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"task_id={task_id}\n")


# ---------------------------------------------------------------- markdown

def _split_title_body(text: str) -> tuple[str, str]:
    """Treat the first H1 as the new title; everything else is the body."""
    lines = text.splitlines()
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^#\s+(.+)$", s)
        if m:
            title = m.group(1).strip()
            body_start = i + 1
        break
    body = "\n".join(lines[body_start:]).strip()
    return title, body or text.strip()


# ---------------------------------------------------------------- subcommands

def cmd_setup(args: argparse.Namespace) -> int:
    _save_config(args.url, args.api_key, args.model or "sonnet")
    print(f"wrote {CONFIG_PATH}")
    # Write a sidecar agent file overriding the rewriter's model if set.
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root and args.model:
        agents_dir = Path(plugin_root) / "agents"
        if agents_dir.exists():
            override = agents_dir / "erpex-rewriter.local.md"
            override.write_text(
                "---\n"
                "name: erpex-rewriter\n"
                "description: Polishes a raw user request into a developer-ready business requirement.\n"
                f"model: {args.model}\n"
                'tools: ["Read", "Glob", "Grep"]\n'
                "---\n"
                "You are a senior product writer. Read the repo for context, then output\n"
                "a single Markdown document whose first H1 is the new task title and\n"
                "whose body is the rewritten business requirement (audience: implementing\n"
                "dev). Do not propose code; do not enter plan mode. Output only the\n"
                "document.\n"
            )
            print(f"wrote {override}")
    return 0


def cmd_get_task(args: argparse.Namespace) -> int:
    task_id = args.task or _read_active_task()
    if not task_id:
        sys.stderr.write("no task id (pass --task or run /erpex-rewrite first)\n")
        return 2
    data = _request("GET", f"/erpex_code_agent/plugin/task/{task_id}")
    print(json.dumps(data, indent=2))
    return 0


def cmd_create_task(args: argparse.Namespace) -> int:
    if not args.project:
        sys.stderr.write("--project is required\n")
        return 2
    body: dict = {"project_id": int(args.project)}
    if args.name:
        body["name"] = args.name
    if args.description:
        body["description"] = args.description
    data = _request("POST", "/erpex_code_agent/plugin/task/create", body)
    task_id = int(data["task_id"])
    _write_active_task(task_id)
    print(json.dumps(data, indent=2))
    return 0


def cmd_submit_rewrite(args: argparse.Namespace) -> int:
    task_id = args.task or _read_active_task()
    if not task_id:
        sys.stderr.write("no task id\n")
        return 2
    text = Path(args.file).read_text()
    title, body = _split_title_body(text)
    cfg = _load_config()
    payload: dict = {
        "task_id": int(task_id),
        "business_requirement": body,
        "model_name": cfg.get("agent", {}).get("model") or "",
    }
    if title:
        payload["title"] = title
    _request("POST", "/erpex_code_agent/plugin/rewrite", payload)
    _write_active_task(int(task_id))
    print(f"rewrite submitted for task {task_id}")
    return 0


def cmd_submit_plan(args: argparse.Namespace) -> int:
    task_id = args.task or _read_active_task()
    if not task_id:
        sys.stderr.write("no task id\n")
        return 2
    text = Path(args.file).read_text()
    cfg = _load_config()
    payload: dict = {
        "task_id": int(task_id),
        "plan_text": text,
        "auto_approve": bool(args.auto_approve),
        "model_name": cfg.get("agent", {}).get("model") or "",
    }
    if args.summary:
        payload["summary"] = args.summary
    if args.claude_session:
        payload["claude_session_id"] = args.claude_session
    data = _request("POST", "/erpex_code_agent/plugin/plan", payload)
    _write_active_task(int(task_id))
    print(json.dumps(data, indent=2))
    return 0


def cmd_fetch_approved_plan(args: argparse.Namespace) -> int:
    task_id = args.task or _read_active_task()
    if not task_id:
        sys.stderr.write("no task id\n")
        return 2
    try:
        data = _request("GET", f"/erpex_code_agent/plugin/plan/approved/{task_id}")
    except HttpError as exc:
        if exc.status == 409:
            sys.stderr.write(exc.body + "\n")
            return 9  # Distinct exit so the slash command can show "still pending".
        raise
    print(json.dumps(data, indent=2))
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    task_id = args.task or _read_active_task()
    if not task_id:
        sys.stderr.write("no task id\n")
        return 2
    success = (args.success or "true").lower() in ("1", "true", "yes", "y", "ok")
    payload = {
        "task_id": int(task_id),
        "kind": args.kind,
        "success": success,
        "summary": args.summary or "",
        "error": args.error or "",
    }
    _request("POST", "/erpex_code_agent/plugin/finish", payload)
    print(f"finish recorded for task {task_id} kind={args.kind}")
    return 0


def cmd_on_exit_plan_mode(args: argparse.Namespace) -> int:
    """PostToolUse hook: read the JSON hook payload from stdin, extract the
    plan, and POST it to ERPEX (with auto_approve so the task advances to
    Implementing). Silent no-op when there's no .erpex/current_task — that
    means the user is in a non-ERPEX plan-mode session and we shouldn't
    interfere.
    """
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.stderr.write("hook: non-JSON stdin, skipping\n")
        return 0
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    plan_text = (tool_input.get("plan") or "").strip()
    if not plan_text:
        return 0
    task_id = _read_active_task()
    if not task_id:
        # Non-ERPEX plan-mode session — leave it alone.
        return 0
    body = {
        "task_id": task_id,
        "plan_text": plan_text,
        "auto_approve": bool(args.auto_approve),
    }
    try:
        _request("POST", "/erpex_code_agent/plugin/plan", body)
    except HttpError as exc:
        sys.stderr.write(f"hook: post failed ({exc})\n")
        return 0  # Never block the user on hook failure.
    sys.stderr.write(f"erpex: plan synced (task {task_id}, auto_approve={args.auto_approve})\n")
    return 0


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="erpex_client")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("setup")
    sp.add_argument("--url", required=True)
    sp.add_argument("--api-key", required=True)
    sp.add_argument("--model", default="sonnet")
    sp.set_defaults(fn=cmd_setup)

    sp = sub.add_parser("get-task")
    sp.add_argument("--task", type=int)
    sp.set_defaults(fn=cmd_get_task)

    sp = sub.add_parser("create-task")
    sp.add_argument("--project", required=True)
    sp.add_argument("--name", default="")
    sp.add_argument("--description", default="")
    sp.set_defaults(fn=cmd_create_task)

    sp = sub.add_parser("submit-rewrite")
    sp.add_argument("--task", type=int)
    sp.add_argument("--file", required=True)
    sp.set_defaults(fn=cmd_submit_rewrite)

    sp = sub.add_parser("submit-plan")
    sp.add_argument("--task", type=int)
    sp.add_argument("--file", required=True)
    sp.add_argument("--summary", default="")
    sp.add_argument("--claude-session", default="")
    sp.add_argument("--auto-approve", action="store_true")
    sp.set_defaults(fn=cmd_submit_plan)

    sp = sub.add_parser("fetch-approved-plan")
    sp.add_argument("--task", type=int)
    sp.set_defaults(fn=cmd_fetch_approved_plan)

    sp = sub.add_parser("finish")
    sp.add_argument("--task", type=int)
    sp.add_argument("--kind", choices=["rewrite", "plan", "implement"], required=True)
    sp.add_argument("--success", default="true")
    sp.add_argument("--summary", default="")
    sp.add_argument("--error", default="")
    sp.set_defaults(fn=cmd_finish)

    sp = sub.add_parser("on-exit-plan-mode")
    sp.add_argument("--auto-approve", action="store_true")
    sp.set_defaults(fn=cmd_on_exit_plan_mode)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
