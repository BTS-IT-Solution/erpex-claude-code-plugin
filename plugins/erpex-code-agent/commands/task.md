---
description: Open an existing ERPEX task by ID and load its description into the session.
argument-hint: "<task_id>"
allowed-tools: ["Bash"]
---

Args: task_id="$1"

## Step 1 — validate task_id

`$1` is required. If empty, abort with this exact message and stop:

```
Usage: /task <task_id>. Example: /task 123
```

Do not write any pointer file in this case.

## Step 2 — bind the task to the session pointer

```
mkdir -p .erpex && echo "task_id=$1" > .erpex/current_task
```

The next user prompt's `UserPromptSubmit` hook will adopt this task and add
`session_id=...` alongside it (see `_ensure_task` in
`scripts/erpex_agentic_client.py`). From that point on, all chat mirroring,
`/plan`, `/rewrite`, `/implement`, and `/approve` operate on task `$1`.

## Step 3 — fetch the task from ERPEX

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" task-get \
    --task-id "$1"
```

The response is JSON of the form:

```
{ "task_id": ..., "name": "...", "description": "...",
  "agentic_description": "...", "project_id": ..., "stage_id": ...,
  "stage_name": "..." }
```

If the command exits non-zero (e.g. 404 — task does not exist, or 401 — bad
API key), remove the pointer so the session does not stay bound to a
non-existent task:

```
rm -f .erpex/current_task
```

Then surface the underlying error to the user and stop.

## Step 4 — show only the description to the user

Pick the description body:

- Prefer `agentic_description` (markdown, the field ERPEX's UI shows).
- If it's empty, fall back to `description`.
- If both are empty, say "Task #$1 has no description yet." and stop.

Print exactly one header line followed by the raw description body — no
JSON, no summary, no extra commentary:

```
Loaded ERPEX task #$1. Description:

<the description body>
```

After this the user can chat normally to start working, or run `/plan`,
`/rewrite`, or `/implement` — they will all target task `$1`.
