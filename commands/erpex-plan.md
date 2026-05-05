---
description: Generate an implementation plan for a task and push it to ERPEX (does not enter plan mode).
argument-hint: "[task_id]"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "Write"]
---

Args: task_id="$1"

## Step 1 — resolve task_id

If `$1` is empty, read it from `.erpex/current_task`. If neither exists,
abort and tell the user: "pass a task_id or run /erpex-rewrite first".
If `$1` is set, write it:
```
mkdir -p .erpex && echo "task_id=$1" > .erpex/current_task
```

## Step 2 — fetch task context

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" get-task --task <id>
```

You'll receive `name`, `business_requirement`, `code_path`, `requires_plan`,
`agent_role`. If `agent_role` is `done` or `review`, abort and tell the
user the task is already past planning.

## Step 3 — produce the plan

**Important: do NOT enter Claude Code plan-mode for this command.** Generate
the plan directly as a Markdown document.

Read the relevant files in `code_path` for context. Then write a plan that
covers:

- A short problem statement (why this change)
- The recommended approach (one approach — not alternatives)
- The critical files to be modified, with paths
- Any existing functions/utilities to reuse
- A verification plan (how to test end-to-end)

Save the plan to `/tmp/erpex-plan-$$.md`.

## Step 4 — push to ERPEX

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" submit-plan --task <id> --file /tmp/erpex-plan-$$.md
```

(Do **not** pass `--auto-approve` here — `/erpex-plan` deliberately leaves
approval to the user via the ERPEX in-chat banner. The auto-approve flag
is only used by the ExitPlanMode hook in `hooks/hooks.json`.)

## Step 5 — record success

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" finish --task <id> --kind plan --success true --summary "plan via /erpex-plan"
```

## Step 6 — confirm

Tell the user the plan is now in ERPEX. They should:
1. Open the task in ERPEX
2. Review the plan in the *Plan* tab
3. Click "Approve & Implement" in the chat banner
4. Then run `/erpex-implement` here to start executing
