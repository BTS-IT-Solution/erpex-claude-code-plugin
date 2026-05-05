---
description: Fetch the approved plan from ERPEX and execute it locally.
argument-hint: "[task_id]"
allowed-tools: ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task"]
---

Args: task_id="$1"

## Step 1 — resolve task_id

If `$1` is empty, read it from `.erpex/current_task`. If neither exists,
abort: "pass a task_id or run /erpex-rewrite first".

## Step 2 — fetch the approved plan

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" fetch-approved-plan --task <id>
```

The helper exits with code **9** if the plan is not yet approved (HTTP
409). When that happens, tell the user to approve in ERPEX first
("Approve & Implement" banner on the task), then re-run `/erpex-implement`.

On success the helper prints JSON with `plan_body`, `business_requirement`,
`code_path`, `branch_name`, `default_branch`. Use these as the brief.

## Step 3 — branch setup

If `branch_name` is set and the user has confirmed creating branches:
```
cd "<code_path>" && git checkout -b "<branch_name>" "<default_branch>" 2>/dev/null || git checkout "<branch_name>"
```
Don't force-create or overwrite — if the branch already exists, just
switch to it.

## Step 4 — execute the plan

Read the plan body and start executing it. Use the standard Edit / Write /
Bash flow. Stay in the user's normal Claude Code session — they are
present and reviewing.

## Step 5 — record finish

When the user signals they're done (or after a clean run):
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" finish --task <id> --kind implement --success true --summary "implementation via /erpex-implement"
```

If something failed:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" finish --task <id> --kind implement --success false --error "<short reason>"
```

Tell the user the run is recorded. They should review the diff and click
*Mark for Review* in the ERPEX UI when they're satisfied.
