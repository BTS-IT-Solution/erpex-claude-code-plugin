---
description: Delegate to erpex-rewriter — polishes the active task's title + description in ERPEX. Self-contained on the sub-agent (minimal Opus tokens).
argument-hint: "[task_id] [project_id]"
allowed-tools: ["Bash", "Task"]
---

Args: task_id="$1"  project_id="$2"

## Step 1 — resolve the active task pointer (cheap)

Order:

1. If `$1` is set, write it as the current pointer:
   ```
   mkdir -p .erpex && echo "task_id=$1" > .erpex/current_task
   ```
2. Else if `.erpex/current_task` already exists (auto-created by chat
   hooks during this session), use it as-is.
3. Else if `$2` is set, ask the helper to create a new task in that
   project:
   ```
   PY="$(command -v python3 || command -v python)"
   "$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" task-create \
       --project-id "$2" --name "Untitled task"
   ```
   The helper writes `.erpex/current_task` automatically.
4. Else abort: "no task pointer; send a chat prompt first (auto-creates
   one) or pass `[task_id] [project_id]`".

## Step 2 — delegate everything to the sub-agent

Invoke the **erpex-rewriter** sub-agent via the `Task` tool. **You do not
read the repo, write any temp file, or run any API call yourself.** The
sub-agent does all of that. Just hand it a brief like:

> Polish the BR for the active task in `.erpex/current_task` and push
> the polished title + body to ERPEX. The repo is the cwd.

The sub-agent's reply is a single confirmation line.

## Step 3 — relay the confirmation

Echo the sub-agent's confirmation back to the user as-is. No restating,
no quoting the BR. The polished BR lives on the task in ERPEX; the user
opens it there.

That's it. Anything more bills the user for Opus tokens unnecessarily.
