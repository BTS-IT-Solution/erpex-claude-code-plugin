---
description: Generate an implementation plan for the active task and push it to ERPEX (does not enter Claude plan-mode).
argument-hint: "[task_id]"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "Write"]
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

## Step 2 — produce the plan

**Important: do NOT enter Claude Code plan-mode for this command.** Generate
the plan directly as a Markdown document. Read the repo for context. The
plan should cover:

- A short problem statement (why this change)
- The recommended approach (one approach — not alternatives)
- The critical files to be modified, with paths
- Any existing functions/utilities to reuse
- A verification plan (how to test end-to-end)

Save the plan to `/tmp/erpex-plan-$$.md`.

## Step 3 — push to ERPEX

```
PY="$(command -v python3 || command -v python)"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" plan-set \
    --task-id "$(grep -oE 'task_id=[0-9]+' .erpex/current_task | cut -d= -f2)" \
    --plan-file /tmp/erpex-plan-$$.md
```

The plan body lands in the task's Plan tab as an `erpex.knowledge.base`
article. Subsequent `plan-set` calls overwrite the body in place.

## Step 4 — confirm

Tell the user the plan is now in ERPEX. They can:
1. Open the task in ERPEX and review the Plan tab.
2. Trigger Claude's plan-mode here (Shift+Tab) when they're ready — exiting
   plan-mode fires the `PreToolUse` hook (re-pushes the plan) and on
   approval the `PostToolUse` hook moves the task to *In Progress*.
3. Or run `/implement` to fetch the plan and execute it now.
