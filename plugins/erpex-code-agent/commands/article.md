---
description: Generate a knowledge-base article from a prompt and create it in ERPEX as a draft.
argument-hint: "<topic or prompt>"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "Write", "AskUserQuestion"]
---

Args: prompt="$ARGUMENTS"

This command does NOT touch `.erpex/current_task` and does NOT set
`agentic_task_id` on the resulting article. Articles are standalone KB
content.

## Step 1 — guard

If `$ARGUMENTS` is empty, abort with: `Usage: /article <topic or prompt>`.

## Step 2 — pick a category

The article needs a category. Resolve one interactively:

```
PY="$(command -v python3 || command -v python)"
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" category-list
```

Branch on the result:

- **No categories at all (`categories: []`)**: ask the user (via
  AskUserQuestion) for a new root-level category name. Then:
  ```
  "$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" \
      category-create --name "<chosen name>"
  ```
  Capture `category_id` from the response.

- **Categories exist**: present the user (via AskUserQuestion) with up to
  four options drawn from the response. Use the category's `display_name`
  as the option label. Always include a `Create new top-level category`
  option. If a chosen category has children (`article_count` aside), the
  user may want to drill in — call `category-list --parent-id <id>` and ask
  again. Stop as soon as you have one `category_id` int.

## Step 3 — generate the article

Write a markdown article tailored to `$ARGUMENTS`. Conventions:

- Strong H1 title on line 1 — this becomes the `name` field (strip the `#`
  before sending). Use Title Case for the H1.
- Body 300–1500 words, structured with H2/H3 sections.
- Optional `[[Title]]` Obsidian-style wikilinks to plausibly-related KB
  articles. ERPEX auto-resolves these on save against existing article
  titles via `_sync_wikilinks()` (case-insensitive); unresolved tokens are
  silently ignored.
- No HTML — markdown only.
- Infer up to 5 lowercase tag names from the topic (e.g. `python`,
  `migrations`, `auth`).

Write the body (without the H1 line) to a temp file:

```
TMP="/tmp/erpex-article-$$.md"
cat > "$TMP" <<'EOF'
<body markdown without the H1>
EOF
```

## Step 4 — create

```
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" article-create \
    --name "<extracted H1 title without the '#'>" \
    --category-id <category_id from Step 2> \
    --body-file "$TMP" \
    --status draft \
    [--tag tag1 --tag tag2 ...]
```

## Step 5 — confirm

Print:

- The new `article_id` from the response
- The article title
- The category's `display_name`
- A reminder that the article is in `draft` status — promote it to
  `published` from the ERPEX Knowledge Base UI when reviewed

Clean up the temp file: `rm -f "$TMP"`.
