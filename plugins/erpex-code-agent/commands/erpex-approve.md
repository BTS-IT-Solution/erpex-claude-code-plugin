---
description: Alias for /erpex-implement — fetch the approved plan and execute it.
argument-hint: "[task_id]"
allowed-tools: ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task"]
---

This command is an alias for `/erpex-implement`. Run it the same way:
delegates to `fetch-approved-plan` and starts executing.

Args: task_id="$1"

Follow the steps in `commands/erpex-implement.md` — same flow:

1. Resolve task_id (from $1 or `.erpex/current_task`).
2. `python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" fetch-approved-plan --task <id>` — exits 9 if not yet approved in ERPEX.
3. Set up the branch if `branch_name` is set.
4. Execute the plan in the current session.
5. `python "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_client.py" finish --task <id> --kind implement --success true|false`.
