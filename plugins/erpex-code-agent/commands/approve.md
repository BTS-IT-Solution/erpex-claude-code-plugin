---
description: Alias for /implement — fetch the plan from ERPEX and execute it.
argument-hint: "[task_id]"
allowed-tools: ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task"]
---

Alias for `/implement`. Follow the steps in `commands/implement.md`:

1. Resolve task_id from `$1` or `.erpex/current_task`.
2. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" plan-get --task-id <id>`.
3. If the response is `{}`, tell the user no plan exists yet (suggest `/plan`
   or Claude's plan-mode). Otherwise treat the `body` as the brief and start
   executing.
4. When finished, optionally advance the task with `task-stage --stage review`.
