---
description: Rewrite a task's business requirement and push it to ERPEX. If no task_id, creates one in the given project.
argument-hint: "[task_id] [project_id]"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "Task", "Write"]
---

Args: task_id="$1"  project_id="$2"

## Step 1 — resolve task_id

If `$1` is empty:
- If `$2` is empty too, abort and tell the user: "pass either a task_id or a project_id".
- Otherwise create a new task by running:
  ```
  python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" create-task --project "$2"
  ```
  Parse the JSON `task_id` from the output. The helper also writes
  `.erpex/current_task` in the cwd; use the value from there going forward.

If `$1` is set, write it to `.erpex/current_task`:
```
mkdir -p .erpex && echo "task_id=$1" > .erpex/current_task
```

## Step 2 — fetch task context

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" get-task --task <id>
```

Use the returned JSON (especially `task_description`, `name`, `code_path`)
to brief the subagent.

## Step 3 — delegate rewriting to the subagent

Invoke the **erpex-rewriter** subagent (via the Task tool). Pass it:
- The original task description and any existing business_requirement
- The project's code_path so it can read the repo for context

The subagent is pinned to the model the user set via `/erpex-setup`.
Capture its final output as a single Markdown document. The first H1 is
the new task title; the rest is the polished business requirement.

Save the output to a temp file, e.g. `/tmp/erpex-rewrite-$$.md`.

## Step 4 — push back to ERPEX

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" submit-rewrite --task <id> --file /tmp/erpex-rewrite-$$.md
```

## Step 5 — record success

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" finish --task <id> --kind rewrite --success true --summary "rewrite via /erpex-rewrite"
```

## Step 6 — confirm

Tell the user: rewrite is in ERPEX, task `<id>` is now in stage *Rewrite*
with `agent_completed_role=rewrite`. Next: open the task in ERPEX, set
*Requires Plan* if needed, and run `/erpex-plan <id>`.
