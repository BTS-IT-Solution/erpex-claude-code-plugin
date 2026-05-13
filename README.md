# erpex-code-agent — Claude Code plugin

Drive ERPEX `project.task` workflow from your own Claude Code session
(CLI or VS Code extension). Companion to the
`erpex_addons/erpex_core_addons/erpex_agentic_code` Odoo module.

## What this gives you

Six slash commands and four hooks that mirror the session into ERPEX:

| Command | What it does |
|---|---|
| `/setup [url] [api_key] [model]` | Stores ERPEX URL, API key, and rewrite-subagent model. Run once per machine. |
| `/task <task_id>` | Opens an existing ERPEX task by ID: fetches its description via `/task/get`, prints it into the chat as context, and binds the current session to that task so the rest of the workflow (`/plan`, `/rewrite`, `/implement`, chat mirroring) targets it instead of creating a new one. |
| `/rewrite [task_id] [project_id]` | Spawns the `erpex-rewriter` subagent and **updates the active task** (auto-created during the session, or supplied) with a polished name + business-requirement description. |
| `/plan [task_id]` | Generates a plan as Markdown and pushes it to the task's Plan tab via `/plan/set`. |
| `/implement [task_id]` (alias `/approve`) | Reads the task's plan via `/plan/get` and executes it in the current session. |

| Hook | What it does |
|---|---|
| **UserPromptSubmit** | Auto-creates a project (folder name) and a task (first-prompt title) if they don't exist yet, then mirrors every prompt into `/chat/user`. |
| **Stop** | Pulls the most recent assistant turn from the transcript and posts it to `/chat/assistant` — Claude's reply lands in the same task's chat panel. |
| **PreToolUse → ExitPlanMode** | When Claude proposes a plan in plan-mode, the hook pushes the plan body to ERPEX **before** the user is asked to approve, so the same plan they're seeing in Claude shows up in the task's Plan tab. |
| **PostToolUse → ExitPlanMode** | Fires only after the user approves the plan in Claude's UI — moves the task to stage **`inprogress`**. |

The net effect: opening Claude Code in a fresh repo and sending a prompt is
enough to materialize a project, a task, the chat history, and (when you
plan-mode) the plan + stage transition in ERPEX, with no manual plumbing.

## Prerequisites

1. **ERPEX module enabled.** `erpex_agentic_code` (≥ 19.0.1.0.0) installed.
   Endpoints used: `/project/create`, `/project/get-or-create` (recommended;
   the plugin falls back to `/project/create` if the lookup endpoint is not
   yet deployed), `/task/create`, `/task/update`, `/task/stage`,
   `/task/get`, `/chat/user`, `/chat/assistant`, `/plan/set`, `/plan/get`.
2. **API key.** Generate one in ERPEX: *Preferences → Account Security →
   New API Key* (any name; copy the key).
3. **Claude Code** with plugin support (`${CLAUDE_PLUGIN_ROOT}` available).
   Python 3.9+ on PATH — the hooks try `python3` first and fall back to
   `python` (a default Windows install of Python only provides `python`,
   not `python3`).

## Install

```bash
# Add the marketplace and install the plugin.
/plugin marketplace add https://github.com/<your-org>/erpex-claude-code-marketplace
/plugin install erpex-code-agent@erpex
```

Or, for local development, point Claude Code at this repo directly:

```bash
/plugin install /path/to/erpex-claude-code-plugin
```

Then configure it once:

```
/setup https://erpex.example.com sk_xxxxxx sonnet
```

This writes `~/.config/erpex-code-agent/plugin.toml` (mode 0600). The `model`
arg controls the model the `erpex-rewriter` subagent uses; pass `opus` if
you want heavier rewriting.

## Per-repo state

The plugin keeps two pointer files in `.erpex/` for the cwd:

```
.erpex/current_project   # plain text: project_id=42
.erpex/current_task      # plain text: task_id=123
```

The hooks read and write these files; you usually don't need to touch them.
Both are populated lazily — the project is resolved (looked up by folder
name, else created) when the first chat message fires, and the task is
created from the first user prompt's text (truncated to 70 chars).

Add `.erpex/` to your global gitignore:

```bash
echo '.erpex/' >> ~/.config/git/ignore
```

## Workflow

### From a fresh repo

```bash
cd <your-repo>
claude
> hello, please add a CSV export to the invoice list
```

That single prompt:

- Creates project `<your-repo>` in ERPEX (or reuses one with the same name).
- Creates a task titled `hello, please add a CSV export to the invoice list`.
- Posts your prompt to `/chat/user`.
- Posts Claude's reply to `/chat/assistant` (when the turn ends).

### Polishing the BR

Once you've narrowed down what you want, run:

```
> /rewrite
```

The rewriter subagent reads the repo for context and emits a polished
title + BR; the helper then **updates** the existing task in place —
new name, new description. No duplicate is created.

### Planning

Two paths, both supported:

**Native plan-mode** (recommended — Shift+Tab to enter):

```
> [iterate on the plan]
[click Approve in plan-mode UI]
```

- `PreToolUse` pushes the plan to the task's Plan tab.
- After you click Approve, `PostToolUse` advances the task to *In Progress*.

**Direct `/plan`** (skips Claude's plan-mode UI):

```
> /plan
> /implement
```

`/plan` writes a Markdown plan and pushes it via `/plan/set`. `/implement`
reads it back via `/plan/get` and starts executing.

## Troubleshooting

**Run `doctor` first.** It prints your config (key redacted), the last 20
lines of the hook log, and probes the API for connectivity:

```bash
# Use `python` instead of `python3` on Windows.
python3 "$(claude plugin path erpex-code-agent)/scripts/erpex_agentic_client.py" doctor
# or, if you know the path:
python3 ~/.claude/plugins/cache/erpex/erpex-code-agent/*/scripts/erpex_agentic_client.py doctor
```

Common findings:

- `not configured. Run /setup first.` → Run `/setup`.
- `CERTIFICATE_VERIFY_FAILED` in the probe → your ERPEX host has an
  incomplete TLS chain (e.g. `bts.erpex.ai` omits Sectigo's intermediate
  cert). Re-run `/setup` with the `insecure` 4th argument:
  `/setup https://bts.erpex.ai sk_xxx sonnet insecure`. This sets
  `verify_ssl = "false"` in the config; the client then uses an
  unverified context for that host.
- Hooks succeed but nothing shows in ERPEX → check
  `tail -f ~/.cache/erpex-code-agent/hook.log` to confirm hooks are firing
  and to see one-line warnings on failures. The hook log is the source of
  truth — Claude Code's UI does not surface hook stderr.
- Duplicate projects appearing for the same repo → upgrade ERPEX to a
  build that ships `/project/get-or-create`. Until then, keep
  `.erpex/current_project` checked in or backed up so the cache survives.

## License

Other proprietary. Same license as the Odoo module.
