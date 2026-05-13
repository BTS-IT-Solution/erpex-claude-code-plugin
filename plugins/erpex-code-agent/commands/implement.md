---
description: Fetch the plan from ERPEX and execute it in the current session.
argument-hint: "[task_id]"
allowed-tools: ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task"]
---

Args: task_id="$1"

## Step 1 — resolve task_id

If `$1` is set, write it as the current pointer:
```
mkdir -p .erpex && echo "task_id=$1" > .erpex/current_task
```

Otherwise read from `.erpex/current_task`. If neither exists, abort: "no
task pointer; send a chat prompt first (auto-creates one) or pass a
task_id".

## Step 2 — fetch the plan

```
PY="$(command -v python3 || command -v python)"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" plan-get \
    --task-id "$(grep -oE 'task_id=[0-9]+' .erpex/current_task | cut -d= -f2)"
```

The response is `{"article_id": ..., "name": "...", "body": "..."}` if a
plan exists, or `{}` if no plan has been written yet.

If `{}`: tell the user there's no plan yet. Options:
- Run `/plan` to author one directly.
- Trigger Claude's plan-mode (Shift+Tab) — the `PreToolUse` hook will push
  the proposed plan to ERPEX automatically.

If the body is present, treat it as the implementation brief.

## Step 3 — execute the plan

Read the `body` text and start executing it with the standard Edit / Write /
Bash flow. Stay in the user's normal Claude Code session — they are present
and reviewing each step.

The chat hooks (`UserPromptSubmit` + `Stop`) will continue to mirror your
prompts and replies into the task's chat panel during execution, so the
audit trail builds itself.

## Step 4 — confirm and hand off

When done, summarize what changed and tell the user:
- The task's chat panel in ERPEX has the full transcript of this run.
- They should review the diff and move the task to *Review* (or *Complete*)
  in ERPEX when satisfied. To do that from here:
  ```
  PY="$(command -v python3 || command -v python)"
  "$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" task-stage \
      --task-id <id> --stage review
  ```
