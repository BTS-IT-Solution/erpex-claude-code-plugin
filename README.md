# erpex-code-agent — Claude Code plugin

Drive ERPEX `project.task` workflow from your own Claude Code session
(CLI or VS Code extension). Companion to the
`erpex_addons/erpex_core_addons/erpex_code_agent` Odoo module.

## What this gives you

Four slash commands and one hook:

| Command | What it does |
|---|---|
| `/erpex-setup [url] [api_key] [model]` | Stores ERPEX URL, API key, and rewrite-subagent model. Run once per machine. |
| `/erpex-rewrite [task_id] [project_id]` | Spawns a Sonnet subagent that turns a rough request into a clean business requirement; pushes it to ERPEX. Creates a new task if `task_id` is missing and a `project_id` is given. |
| `/erpex-plan [task_id]` | Reads the task's BR, generates a plan in markdown, pushes it to ERPEX as a plan_proposal. The user reviews and clicks *Approve & Implement* in the ERPEX UI. |
| `/erpex-implement [task_id]` (alias `/erpex-approve`) | Fetches the approved plan from ERPEX and starts executing. Returns 409 if not yet approved. |
| **PostToolUse hook on `ExitPlanMode`** | When you click *Approve* in Claude Code's plan-mode UI, the hook auto-pushes the plan to ERPEX **and** advances the task to *Implementing* (no second click needed). |

## Prerequisites

1. **ERPEX module enabled.** `erpex_code_agent` ≥ 19.0.1.11.0 installed and
   *Settings → General Settings → Code Agent → Code Agent Mode* set to
   **Claude Code Plugin** (the default).
2. **API key.** Generate one in ERPEX: *Preferences → Account Security →
   New API Key* (any name; copy the key).
3. **Claude Code** ≥ a version with plugins / `${CLAUDE_PLUGIN_ROOT}` (any
   recent CLI or VS Code extension). Python 3.9+ on PATH.

## Install

```bash
# Add the marketplace (separate repo) and install the plugin.
/plugin marketplace add https://github.com/<your-org>/erpex-claude-code-marketplace
/plugin install erpex-code-agent@erpex
```

Or, for local development, point Claude Code at this repo directly:

```bash
/plugin install /path/to/erpex-claude-code-plugin
```

Then configure it once:

```
/erpex-setup https://erpex.example.com sk_xxxxxx sonnet
```

This writes `~/.config/erpex-code-agent/plugin.toml` (mode 0600). The `model`
arg controls the model the `erpex-rewriter` subagent uses; pass `opus` if
you want heavier rewriting.

## Per-repo setup

Inside each repository whose `code_path` matches a project in ERPEX, the
plugin keeps a tiny pointer file:

```
.erpex/current_task     # plain text: task_id=123
```

Add it to your global gitignore:

```bash
echo '.erpex/' >> ~/.config/git/ignore
```

Or per-repo in `.gitignore`.

## Workflow

### Starting from a free-form request

```
cd <your-repo>
claude
> /erpex-rewrite "" 7      # task_id="" → create new in project 7
```

The subagent rewrites your request as a developer-ready BR and pushes it
to ERPEX. The task lands in stage *Rewrite*. Open it in ERPEX, set
*Requires Plan* if needed.

### Starting from an existing task

```
> /erpex-rewrite 1234         # rewrite the BR for task 1234
> /erpex-plan 1234            # generate + push a plan
                              # → user clicks Approve in ERPEX
> /erpex-implement 1234       # fetch approved plan, start executing
```

### Starting from native plan-mode (skips /erpex-plan)

If you'd rather use Claude Code's built-in plan-mode:

```
> /erpex-rewrite 1234         # writes .erpex/current_task
> /plan                       # native plan-mode
                              # ... iterate ...
                              # click Approve in plan-mode UI
                              # → hook pushes plan + auto-advances ERPEX to Implementing
```

The PostToolUse hook on `ExitPlanMode` reads `.erpex/current_task`,
extracts the approved plan, and POSTs it with `auto_approve=true`.

## Troubleshooting

- `not configured. Run /erpex-setup first.` → Run `/erpex-setup`.
- `403 plugin mode disabled` → Your ERPEX admin set the mode to *daemon*.
  Ask them to flip *Settings → General Settings → Code Agent → Code Agent
  Mode* to *Claude Code Plugin*.
- `409 Plan is not yet approved` → Click *Approve & Implement* on the task
  in ERPEX (the chat banner), then re-run `/erpex-implement`.
- Hook fires but says `non-JSON stdin, skipping` → harmless; means
  Claude Code didn't pass a structured payload that turn.

## License

Other proprietary. Same license as the Odoo module.
