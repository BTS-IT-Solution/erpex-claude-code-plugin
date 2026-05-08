---
description: Polish the current task's business requirement and update the task name + description in ERPEX.
argument-hint: "[task_id] [project_id]"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "Task", "Write"]
---

Args: task_id="$1"  project_id="$2"

## Step 1 — resolve task_id

In order:

1. If `$1` is set, write it as the current task pointer:
   ```
   mkdir -p .erpex && echo "task_id=$1" > .erpex/current_task
   ```
2. Else if `.erpex/current_task` already exists (e.g. created by the chat
   hooks during this session), use it.
3. Else if `$2` is set, create a new task in that project:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" task-create \
       --project-id "$2" --name "Untitled task"
   ```
   The helper writes `.erpex/current_task` automatically.
4. Else abort with: "no task pointer; send a chat prompt first (auto-creates
   one) or pass `[task_id] [project_id]`".

Read the active id back from `.erpex/current_task` for the rest of this command.

## Step 2 — gather context for the subagent

Read the repo (Glob/Grep/Read) and the active `.erpex/current_task` file as
needed. The subagent has `Read`, `Glob`, `Grep` only — pass it the original
free-form text the user described AND the path to this repo so it can skim
for naming and conventions.

## Step 3 — delegate rewriting to the subagent

Invoke the **erpex-rewriter** subagent via the Task tool. Pin its instructions:

- Output **one** Markdown document.
- First H1 is the new task title (≤ 70 chars, imperative).
- Body is the polished business requirement (no code, no plan-mode).

Save the subagent's output to a temp file: `/tmp/erpex-rewrite-$$.md`.

## Step 4 — update the task in place

Split the H1 from the body in the helper script's logic by extracting them
yourself (head + tail of the file) into shell variables `TITLE` and
`BODY`, then:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" task-update \
    --task-id "$(grep -oE 'task_id=[0-9]+' .erpex/current_task | cut -d= -f2)" \
    --field name="$TITLE" \
    --field description="$BODY"
```

This is the key behavioral change: we **update** the existing task (whether
it was auto-created by the chat hooks, supplied by the user, or just made
in step 1) rather than creating a new one.

## Step 5 — confirm

Tell the user the task name + description in ERPEX have been updated. Next
recommended step: enter Claude's plan-mode (Shift+Tab) so the
`PreToolUse`/`PostToolUse` hooks push the plan and advance the stage to
*In Progress* on approval. Or run `/plan` to author a plan directly.
