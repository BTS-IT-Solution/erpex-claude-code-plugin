#!/usr/bin/env python3
"""HTTP client for the erpex_agentic_code module's `/erpex_agentic_code/api/*`
endpoints. Stdlib-only (urllib + tomllib) so the plugin runs on a fresh
machine without `pip install`.

Config lives at `~/.config/erpex-code-agent/plugin.toml` (written by `setup`).

Subcommands:

    setup            --url <u> --api-key <k> [--model <m>] [--insecure]
    project-create   --name "Foo"
    task-create      --project-id 12 --name "T1" [--description ...]
                                                 [--agentic-description ...]
                                                 [--parent-id 9]
    task-update      --task-id 33 --field name="New" [--field priority=1 ...]
    task-stage       --task-id 33 --stage plan
    chat-user        --task-id 33 --content "..." [--sender "Ahmed"]
    chat-assistant   --task-id 33 --content "..."
    plan-set         --task-id 33 (--plan-text "..." | --plan-file plan.md)
    plan-get         --task-id 33
    task-get         --task-id 33

Hook subcommands (read JSON payload from stdin, never block the user):

    hook-user-prompt        UserPromptSubmit  → ensure task, POST /chat/user
    hook-stop               Stop              → POST /chat/assistant from
                                                last assistant turn in
                                                transcript_path
    hook-pre-exit-plan      PreToolUse        → ensure task, POST /plan/set
                            (matcher          (no auto-approve)
                            ExitPlanMode)
    hook-post-exit-plan     PostToolUse       → POST /task/stage inprogress
                            (matcher
                            ExitPlanMode)

Diagnostics:

    doctor          prints config (key redacted), tail of hook log, and
                    runs a connectivity probe against the API. Always 0.

Exit codes:
    0  success (or hook safe-exit on failure)
    1  client error (config / validation / unknown subcommand)
    2  server error (4xx / 5xx) for non-hook subcommands
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore


CONFIG_DIR = Path(os.path.expanduser("~/.config/erpex-code-agent"))
CONFIG_PATH = CONFIG_DIR / "plugin.toml"
API_BASE = "/erpex_agentic_code/api"


# ---------------------------------------------------------------- config

def _parse_toml(text: str) -> dict:
    if tomllib is not None:
        return tomllib.loads(text)
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
            f"erpex-agentic-client: not configured. Run /setup first.\n"
            f"(expected config at {CONFIG_PATH})\n"
        )
        sys.exit(1)
    cfg = _parse_toml(CONFIG_PATH.read_text())
    if not cfg.get("odoo", {}).get("url") or not cfg.get("odoo", {}).get("api_key"):
        sys.stderr.write(
            f"erpex-agentic-client: config at {CONFIG_PATH} is missing "
            f"[odoo].url or [odoo].api_key.\n"
        )
        sys.exit(1)
    return cfg


def _save_config(url: str, api_key: str, model: str,
                 verify_ssl: bool = True) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    body = (
        '[odoo]\n'
        f'url = "{url}"\n'
        f'api_key = "{api_key}"\n'
        f'verify_ssl = "{"true" if verify_ssl else "false"}"\n'
        '\n'
        '[agent]\n'
        f'model = "{model}"\n'
    )
    CONFIG_PATH.write_text(body)
    try:
        os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows / odd FS — best-effort.


def _verify_ssl(cfg: dict) -> bool:
    raw = cfg.get("odoo", {}).get("verify_ssl")
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("false", "0", "no", "off")


# ---------------------------------------------------------------- HTTP

class HttpError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _request(
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
) -> dict:
    cfg = _load_config()
    base_url = cfg["odoo"]["url"].rstrip("/")
    url = base_url + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {
        "Authorization": "Bearer " + cfg["odoo"]["api_key"],
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    ctx = None if _verify_ssl(cfg) else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        raise HttpError(exc.code, raw) from exc


def _api_call(method: str, endpoint: str, body: dict | None = None,
              query: dict | None = None) -> dict:
    return _request(method, API_BASE + endpoint, body=body, query=query)


def _print_json(data: dict) -> None:
    print(json.dumps(data, indent=2))


# ---------------------------------------------------------------- session pointers

def _repo_root() -> Path:
    return Path.cwd()


def _erpex_dir() -> Path:
    return _repo_root() / ".erpex"


def _active_task_path() -> Path:
    return _erpex_dir() / "current_task"


def _active_project_path() -> Path:
    return _erpex_dir() / "current_project"


def _read_pointer(path: Path, key: str) -> int | None:
    if not path.exists():
        return None
    txt = path.read_text().strip()
    m = re.search(rf"{key}\s*=\s*(\d+)", txt)
    if m:
        return int(m.group(1))
    if txt.isdigit():
        return int(txt)
    return None


def _write_pointer(path: Path, key: str, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{key}={value}\n")


def _read_active_task() -> tuple[int | None, str | None]:
    """Return (task_id, session_id). session_id is None for legacy
    (single-line `task_id=N`) pointer files written before the session-scoped
    upgrade — those are treated as 'no session' so the next session creates
    its own fresh task."""
    path = _active_task_path()
    if not path.exists():
        return None, None
    txt = path.read_text()
    m = re.search(r"task_id\s*=\s*(\d+)", txt)
    tid = int(m.group(1)) if m else None
    if tid is None:
        s = txt.strip()
        if s.isdigit():
            tid = int(s)
    m = re.search(r"session_id\s*=\s*(\S+)", txt)
    sid = m.group(1) if m else None
    return tid, sid


def _write_active_task(task_id: int, session_id: str = "") -> None:
    path = _active_task_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"task_id={task_id}\n"
    if session_id:
        body += f"session_id={session_id}\n"
    path.write_text(body)


def _read_active_project() -> int | None:
    return _read_pointer(_active_project_path(), "project_id")


def _write_active_project(project_id: int) -> None:
    _write_pointer(_active_project_path(), "project_id", project_id)


def _last_stop_hash_path() -> Path:
    return _erpex_dir() / "last_stop_hash"


def _read_last_stop_hash() -> tuple[int | None, str | None]:
    """Return (task_id, content_hash) of the most recently posted Stop, or
    (None, None) if no record. Used to short-circuit duplicate Stop fires
    that would otherwise post the same assistant text twice."""
    path = _last_stop_hash_path()
    if not path.exists():
        return None, None
    txt = path.read_text()
    m_t = re.search(r"task_id\s*=\s*(\d+)", txt)
    m_h = re.search(r"content_hash\s*=\s*([0-9a-fA-F]+)", txt)
    tid = int(m_t.group(1)) if m_t else None
    h = m_h.group(1) if m_h else None
    return tid, h


def _write_last_stop_hash(task_id: int, content_hash: str) -> None:
    path = _last_stop_hash_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"task_id={task_id}\ncontent_hash={content_hash}\n")


def _folder_name() -> str:
    return _repo_root().name or "untitled-project"


# ---------------------------------------------------------------- text helpers

def _truncate_title(text: str, n: int = 70) -> str:
    """Sanitize a free-form prompt into a one-line task title."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) > n:
        s = s[: n - 1].rstrip() + "…"
    return s or "Untitled task"


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


# ---------------------------------------------------------------- ensure helpers

def _ensure_project() -> int:
    """Return a project_id for the current repo, creating one if needed."""
    pid = _read_active_project()
    if pid:
        return pid
    name = _folder_name()
    try:
        data = _api_call("POST", "/project/get-or-create", {"name": name})
    except HttpError as exc:
        if exc.status == 404:
            # Endpoint not deployed yet — fall back to plain create.
            data = _api_call("POST", "/project/create", {"name": name})
        else:
            raise
    pid = int(data["project_id"])
    _write_active_project(pid)
    return pid


def _ensure_task(initial_title: str, session_id: str = "") -> int:
    """Return a task_id for the current session, creating one if needed.

    Session-scoped: a new Claude Code session gets a fresh task even when
    the repo already has a `.erpex/current_task` from an earlier session.
    Slash commands (no session_id available) trust the cached pointer."""
    cached_tid, cached_sid = _read_active_task()
    if cached_tid and cached_sid and session_id and cached_sid == session_id:
        return cached_tid
    if cached_tid and not session_id:
        # Slash-command path: no session context — reuse whatever's cached.
        return cached_tid
    if cached_tid and session_id and not cached_sid:
        # Pointer was written by a slash command (e.g. /task, /plan, /implement)
        # before any user prompt — it has no session binding yet. Adopt the
        # existing task for THIS session instead of spawning a fresh one.
        _write_active_task(cached_tid, session_id)
        return cached_tid
    # Either no pointer yet OR pointer belongs to a different session.
    pid = _ensure_project()
    body = {"project_id": pid, "name": initial_title or "Untitled task"}
    data = _api_call("POST", "/task/create", body)
    tid = int(data["task_id"])
    _write_active_task(tid, session_id)
    return tid


# ---------------------------------------------------------------- args

def _parse_field_kv(items: list[str]) -> dict:
    """Parse `--field key=value` pairs. Values starting with `[` or `{` are
    JSON-decoded so the caller can pass M2M command tuples; integers are
    coerced; everything else stays a string.
    """
    out: dict = {}
    for item in items or []:
        if "=" not in item:
            sys.stderr.write(f"--field requires KEY=VALUE, got: {item!r}\n")
            sys.exit(1)
        key, _, value = item.partition("=")
        key = key.strip()
        value = value.strip()
        if value and value[0] in "[{":
            try:
                out[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            out[key] = int(value)
            continue
        if value.lower() in ("true", "false"):
            out[key] = value.lower() == "true"
            continue
        out[key] = value
    return out


# ---------------------------------------------------------------- subcommands (regular)

def cmd_setup(args: argparse.Namespace) -> int:
    _save_config(args.url, args.api_key, args.model or "sonnet",
                 verify_ssl=not args.insecure)
    print(f"wrote {CONFIG_PATH} (verify_ssl={'false' if args.insecure else 'true'})")
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


def cmd_project_create(args: argparse.Namespace) -> int:
    data = _api_call("POST", "/project/create", {"name": args.name})
    _print_json(data)
    return 0


def cmd_task_create(args: argparse.Namespace) -> int:
    body: dict = {"project_id": int(args.project_id), "name": args.name}
    if args.description:
        body["description"] = args.description
    if args.agentic_description:
        body["agentic_description"] = args.agentic_description
    if args.parent_id:
        body["parent_id"] = int(args.parent_id)
    data = _api_call("POST", "/task/create", body)
    if "task_id" in data:
        _write_active_task(int(data["task_id"]))
    _print_json(data)
    return 0


def cmd_task_update(args: argparse.Namespace) -> int:
    fields = _parse_field_kv(args.field)
    if not fields:
        sys.stderr.write("at least one --field KEY=VALUE is required\n")
        return 1
    body: dict = {"task_id": int(args.task_id)}
    body.update(fields)
    data = _api_call("POST", "/task/update", body)
    _print_json(data)
    return 0


def cmd_task_stage(args: argparse.Namespace) -> int:
    body = {"task_id": int(args.task_id), "stage_key": args.stage}
    data = _api_call("POST", "/task/stage", body)
    _print_json(data)
    return 0


def cmd_chat_user(args: argparse.Namespace) -> int:
    body: dict = {"task_id": int(args.task_id), "content": args.content}
    if args.sender:
        body["sender_name"] = args.sender
    data = _api_call("POST", "/chat/user", body)
    _print_json(data)
    return 0


def cmd_chat_assistant(args: argparse.Namespace) -> int:
    body = {"task_id": int(args.task_id), "content": args.content}
    data = _api_call("POST", "/chat/assistant", body)
    _print_json(data)
    return 0


def cmd_plan_set(args: argparse.Namespace) -> int:
    if args.plan_file:
        plan_text = Path(args.plan_file).read_text()
    elif args.plan_text is not None:
        plan_text = args.plan_text
    else:
        sys.stderr.write("either --plan-text or --plan-file is required\n")
        return 1
    body = {"task_id": int(args.task_id), "plan_text": plan_text}
    data = _api_call("POST", "/plan/set", body)
    _print_json(data)
    return 0


def cmd_plan_get(args: argparse.Namespace) -> int:
    data = _api_call("GET", "/plan/get", query={"task_id": int(args.task_id)})
    _print_json(data)
    return 0


def cmd_task_get(args: argparse.Namespace) -> int:
    data = _api_call("GET", "/task/get", query={"task_id": int(args.task_id)})
    _print_json(data)
    return 0


# ---------------------------------------------------------------- subcommands (hooks)

HOOK_LOG_DIR = Path(os.path.expanduser("~/.cache/erpex-code-agent"))
HOOK_LOG_PATH = HOOK_LOG_DIR / "hook.log"


def _hook_log(line: str) -> None:
    """Best-effort append to ~/.cache/erpex-code-agent/hook.log. Silent on
    filesystem errors so logging never breaks the hook itself."""
    try:
        HOOK_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with HOOK_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {line}\n")
    except OSError:
        pass


def _hook_warn(msg: str) -> None:
    sys.stderr.write(f"erpex hook: {msg}\n")
    _hook_log(f"WARN {msg}")


def _hook_payload() -> dict:
    raw = sys.stdin.read() or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _hook_safe(name: str, fn) -> int:
    """Wrapper: never raise out of a hook. Always return 0 so Claude isn't
    blocked by ERPEX flakiness or a missing /setup. Log entry/exit so the
    user can `tail -f ~/.cache/erpex-code-agent/hook.log` to diagnose."""
    _hook_log(f"{name} fired (cwd={os.getcwd()})")
    try:
        fn()
        _hook_log(f"{name} ok")
    except HttpError as exc:
        _hook_warn(f"{name}: {exc}")
    except SystemExit:
        # _load_config calls sys.exit(1) when not configured — note and skip.
        _hook_log(f"{name} skipped: not configured (run /setup)")
    except Exception as exc:  # pylint: disable=broad-except
        _hook_warn(f"{name}: unexpected: {exc}")
    return 0


def cmd_hook_user_prompt(_args: argparse.Namespace) -> int:
    def _go() -> None:
        payload = _hook_payload()
        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            _hook_log("user-prompt noop reason=empty-prompt")
            return
        sid = (payload.get("session_id") or "").strip()
        prev_tid, _ = _read_active_task()
        tid = _ensure_task(_truncate_title(prompt), sid)
        resp = _api_call("POST", "/chat/user",
                         {"task_id": tid, "content": prompt})
        action = "reused" if prev_tid == tid else "created"
        _hook_log(
            f"user-prompt posted task={tid} ({action}) len={len(prompt)} "
            f"message_id={resp.get('message_id')}"
        )
    return _hook_safe("user-prompt", _go)


def _is_real_user_entry(entry: dict) -> bool:
    """A *real* user entry is a human prompt, not a tool_result wrapper.

    Anthropic's API records tool results as `role=user` entries with
    content[].type == "tool_result". Those should NOT be the anchor for
    "everything Claude said since the user spoke last" — the human user
    is what we mean by user."""
    msg = entry.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        has_tool_result = any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content
        )
        if has_tool_result:
            return False
        return any(
            isinstance(b, dict) and b.get("type") in ("text", "image", "document")
            for b in content
        )
    return False


def _last_assistant_text(transcript_path: str) -> str:
    """Return the assistant turn's full text content.

    Walks the JSONL transcript, finds the most recent *real* user entry
    (i.e. a human prompt — not a tool_result wrapper), and concatenates
    every text block from every assistant entry that comes after it.
    Survives multi-message assistant turns interleaved with tool_use ↔
    tool_result exchanges, which is the default for any non-trivial
    Claude turn."""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    entries: list[dict] = []
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    last_user_idx = -1
    for i, e in enumerate(entries):
        if _is_real_user_entry(e):
            last_user_idx = i

    chunks: list[str] = []
    for e in entries[last_user_idx + 1:]:
        msg = e.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            if content.strip():
                chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        chunks.append(text)
    return "\n\n".join(chunks).strip()


def _last_assistant_text_resilient(transcript_path: str,
                                   retries: int = 4,
                                   delay_s: float = 0.5) -> str:
    """Read the transcript with retry-on-empty.

    Stop hooks can fire microseconds before Claude Code finishes flushing
    the assistant entry to the JSONL. Retrying for a couple of seconds
    eliminates that flush race in practice. The hook timeout in
    hooks.json is 15s, so 2-3s of total backoff is well within budget."""
    text = _last_assistant_text(transcript_path)
    if text:
        return text
    for _ in range(retries):
        time.sleep(delay_s)
        text = _last_assistant_text(transcript_path)
        if text:
            return text
    return ""


def cmd_hook_stop(_args: argparse.Namespace) -> int:
    def _go() -> None:
        payload = _hook_payload()
        transcript = payload.get("transcript_path") or payload.get("transcriptPath") or ""
        if not transcript:
            _hook_log("stop noop reason=no-transcript-path")
            return
        # Retry briefly to absorb the JSONL flush race — Claude Code can
        # fire Stop microseconds before its final assistant entry hits
        # disk, leaving the parser to see no text.
        text = _last_assistant_text_resilient(transcript)
        if not text:
            _hook_log(f"stop noop reason=empty-text transcript={transcript}")
            return
        cached_tid, cached_sid = _read_active_task()
        if not cached_tid:
            _hook_log("stop noop reason=no-cached-task")
            return
        sid = (payload.get("session_id") or "").strip()
        if cached_sid and sid and cached_sid != sid:
            _hook_log(
                f"stop noop reason=session-mismatch "
                f"cached_sid={cached_sid[:8]}… payload_sid={sid[:8]}…"
            )
            return
        # Idempotency: skip if we already posted this exact text for this
        # task. Stop hooks can fire more than once per turn (e.g. when the
        # transcript writer races us); without this guard we'd double-post.
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        prev_tid, prev_hash = _read_last_stop_hash()
        if prev_tid == cached_tid and prev_hash == content_hash:
            _hook_log(
                f"stop noop reason=duplicate task={cached_tid} "
                f"hash={content_hash[:8]}…"
            )
            return
        resp = _api_call("POST", "/chat/assistant",
                         {"task_id": cached_tid, "content": text})
        _write_last_stop_hash(cached_tid, content_hash)
        _hook_log(
            f"stop posted task={cached_tid} len={len(text)} "
            f"message_id={resp.get('message_id')}"
        )
    return _hook_safe("stop", _go)


_PLAN_MARKER_RE = re.compile(
    r"\A\s*<!--\s*erpex-plan:\s*(update|new-child)\s*-->\s*\n?",
    re.IGNORECASE,
)


def _split_plan_marker(plan_text: str) -> tuple[str | None, str]:
    """Strip a leading `<!-- erpex-plan: update|new-child -->` marker from the
    plan body and return `(mode, cleaned_text)`. The marker is how Claude (in
    plan mode, with no Bash/Write available) communicates the user's choice
    between updating the current plan vs forking a child task.

    If no marker is present, returns `(None, plan_text)`."""
    m = _PLAN_MARKER_RE.match(plan_text)
    if not m:
        return None, plan_text
    mode = m.group(1).lower()
    return mode, plan_text[m.end():]


def _task_has_plan(task_id: int) -> bool:
    """Best-effort probe: does this task already have a plan article?
    Treats every failure mode (HTTP 404, transient server error, malformed
    body) as 'no existing plan' so a flaky probe never blocks the user."""
    try:
        data = _api_call("GET", "/plan/get", query={"task_id": task_id})
    except (HttpError, urllib.error.URLError, ssl.SSLError, OSError):
        return False
    return bool(data.get("body"))


_PRE_EXIT_PLAN_DENY_REASON = (
    "ERPEX: this task already has a plan. Before re-approving, ask the user "
    "via AskUserQuestion which they want — options must be exactly:\n"
    "  1. 'Update existing plan' → prepend the line "
    "`<!-- erpex-plan: update -->` as the very first line of the plan markdown.\n"
    "  2. 'Create new child task' → prepend the line "
    "`<!-- erpex-plan: new-child -->` as the very first line of the plan markdown.\n"
    "Then call ExitPlanMode again with the tagged plan."
)


def _pre_exit_plan_deny(reason: str) -> None:
    """Print the JSON envelope that tells Claude Code to deny ExitPlanMode
    and pass `reason` back to Claude as the deny rationale."""
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.stdout.flush()


def cmd_hook_pre_exit_plan(_args: argparse.Namespace) -> int:
    def _go() -> None:
        payload = _hook_payload()
        tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
        plan_raw = (tool_input.get("plan") or "").strip()
        if not plan_raw:
            _hook_log("pre-exit-plan noop reason=empty-plan")
            return
        mode, plan_text = _split_plan_marker(plan_raw)
        sid = (payload.get("session_id") or "").strip()
        first_line = next(
            (ln.strip() for ln in plan_text.splitlines() if ln.strip()),
            "Plan",
        )
        title = _truncate_title(re.sub(r"^#+\s*", "", first_line))
        tid = _ensure_task(title, sid)

        if mode == "new-child":
            pid = _ensure_project()
            data = _api_call("POST", "/task/create",
                             {"project_id": pid, "parent_id": tid, "name": title})
            new_tid = int(data["task_id"])
            _write_active_task(new_tid, sid)
            resp = _api_call("POST", "/plan/set",
                             {"task_id": new_tid, "plan_text": plan_text})
            _hook_log(
                f"pre-exit-plan new-child parent={tid} new={new_tid} "
                f"len={len(plan_text)} article_id={resp.get('article_id')}"
            )
            return

        if mode is None and _task_has_plan(tid):
            _pre_exit_plan_deny(_PRE_EXIT_PLAN_DENY_REASON)
            _hook_log(f"pre-exit-plan denied reason=marker-missing task={tid}")
            return

        resp = _api_call("POST", "/plan/set",
                         {"task_id": tid, "plan_text": plan_text})
        _hook_log(
            f"pre-exit-plan posted task={tid} mode={mode or 'first-plan'} "
            f"len={len(plan_text)} article_id={resp.get('article_id')}"
        )
    return _hook_safe("pre-exit-plan", _go)


def cmd_hook_post_exit_plan(_args: argparse.Namespace) -> int:
    def _go() -> None:
        payload = _hook_payload()
        cached_tid, cached_sid = _read_active_task()
        if not cached_tid:
            _hook_log("post-exit-plan noop reason=no-cached-task")
            return
        sid = (payload.get("session_id") or "").strip()
        if cached_sid and sid and cached_sid != sid:
            _hook_log(
                f"post-exit-plan noop reason=session-mismatch "
                f"cached_sid={cached_sid[:8]}… payload_sid={sid[:8]}…"
            )
            return
        resp = _api_call("POST", "/task/stage",
                         {"task_id": cached_tid, "stage_key": "inprogress"})
        _hook_log(
            f"post-exit-plan posted task={cached_tid} "
            f"stage_id={resp.get('stage_id')} stage_name={resp.get('stage_name')}"
        )
    return _hook_safe("post-exit-plan", _go)


# ---------------------------------------------------------------- doctor

def _redact_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "***"
    return key[:4] + "…" + key[-4:]


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Print config (redacted), tail of hook log, and connectivity probe.
    Always exits 0 — this is for diagnosis, not for failing CI."""
    print(f"config: {CONFIG_PATH}")
    if not CONFIG_PATH.exists():
        print("  (no config — run /setup)")
        return 0
    try:
        cfg = _parse_toml(CONFIG_PATH.read_text())
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  parse error: {exc}")
        return 0
    odoo = cfg.get("odoo", {})
    print(f"  url:        {odoo.get('url') or '(missing)'}")
    print(f"  api_key:    {_redact_key(odoo.get('api_key') or '')}")
    print(f"  verify_ssl: {_verify_ssl(cfg)}")
    print(f"  model:      {cfg.get('agent', {}).get('model') or '(unset)'}")

    print(f"\nhook log: {HOOK_LOG_PATH}")
    if HOOK_LOG_PATH.exists():
        try:
            lines = HOOK_LOG_PATH.read_text(errors="replace").splitlines()
            for line in lines[-20:]:
                print(f"  {line}")
        except OSError as exc:
            print(f"  read error: {exc}")
    else:
        print("  (empty — no hook has fired yet)")

    print("\nconnectivity probe: GET /plan/get?task_id=0")
    try:
        _api_call("GET", "/plan/get", query={"task_id": 0})
        print("  ok (server reachable, auth valid)")
    except HttpError as exc:
        if exc.status == 404:
            print("  ok (server reachable, auth valid; no task #0 — expected)")
        else:
            print(f"  server replied {exc.status}: {exc.body[:200]}")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  failed: {exc}")
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            print("  → re-run /setup with the `insecure` flag for hosts with "
                  "an incomplete cert chain.")
    return 0


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="erpex_agentic_client")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("setup")
    sp.add_argument("--url", required=True)
    sp.add_argument("--api-key", required=True)
    sp.add_argument("--model", default="sonnet")
    sp.add_argument("--insecure", action="store_true",
                    help="Skip TLS cert verification (set verify_ssl=false). "
                         "Use for ERPEX hosts with an incomplete cert chain.")
    sp.set_defaults(fn=cmd_setup)

    sp = sub.add_parser("project-create")
    sp.add_argument("--name", required=True)
    sp.set_defaults(fn=cmd_project_create)

    sp = sub.add_parser("task-create")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--description", default="")
    sp.add_argument("--agentic-description", default="")
    sp.add_argument("--parent-id", default="")
    sp.set_defaults(fn=cmd_task_create)

    sp = sub.add_parser("task-update")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--field", action="append", default=[],
                    help="KEY=VALUE; pass multiple times. JSON values "
                         "(starting with [ or {) are decoded.")
    sp.set_defaults(fn=cmd_task_update)

    sp = sub.add_parser("task-stage")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--stage", required=True,
                    choices=["draft", "todo", "plan", "inprogress",
                             "review", "complete"])
    sp.set_defaults(fn=cmd_task_stage)

    sp = sub.add_parser("chat-user")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--content", required=True)
    sp.add_argument("--sender", default="")
    sp.set_defaults(fn=cmd_chat_user)

    sp = sub.add_parser("chat-assistant")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--content", required=True)
    sp.set_defaults(fn=cmd_chat_assistant)

    sp = sub.add_parser("plan-set")
    sp.add_argument("--task-id", required=True)
    grp = sp.add_mutually_exclusive_group(required=True)
    grp.add_argument("--plan-text")
    grp.add_argument("--plan-file")
    sp.set_defaults(fn=cmd_plan_set)

    sp = sub.add_parser("plan-get")
    sp.add_argument("--task-id", required=True)
    sp.set_defaults(fn=cmd_plan_get)

    sp = sub.add_parser("task-get")
    sp.add_argument("--task-id", required=True)
    sp.set_defaults(fn=cmd_task_get)

    sp = sub.add_parser("hook-user-prompt")
    sp.set_defaults(fn=cmd_hook_user_prompt)

    sp = sub.add_parser("hook-stop")
    sp.set_defaults(fn=cmd_hook_stop)

    sp = sub.add_parser("hook-pre-exit-plan")
    sp.set_defaults(fn=cmd_hook_pre_exit_plan)

    sp = sub.add_parser("hook-post-exit-plan")
    sp.set_defaults(fn=cmd_hook_post_exit_plan)

    sp = sub.add_parser("doctor")
    sp.set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except HttpError as exc:
        sys.stderr.write(f"server error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
