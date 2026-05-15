---
description: Build a multi-article wiki from a topic prompt (Karpathy-inspired second-memory pattern).
argument-hint: "<topic>"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "Write", "AskUserQuestion"]
---

Args: topic="$ARGUMENTS"

Builds a topic into a Karpathy-style wiki: 1 root category + three fixed
subs (`Entities`, `Concepts`, `Synthesis`) + 5–15 cross-linked draft
articles + an `<Root> Index` page. Inspired by:
<https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f> and the
operational canon at
<https://github.com/NicholasSpisak/second-brain>.

This command does NOT touch `.erpex/current_task` and does NOT set
`agentic_task_id`. An interrupted Pass 2 leaves some articles with stub
bodies — recoverable by re-running `article-update` manually.

## Step 1 — guard

If `$ARGUMENTS` is empty, abort with: `Usage: /build-wiki <topic>`.

```
PY="$(command -v python3 || command -v python)"
CLIENT="${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py"
```

ERPEX auto-tracks `create_date`, `write_date`, `erpex_last_content_update`,
and `erpex_owner_id` for every article — the slash command never has to
think about them.

## Step 2 — pick the wiki root

Propose a root-category name from `$ARGUMENTS` (Title Case). Ask the user
via AskUserQuestion:

- **A. Create new top-level category `<proposed name>`** (default)
- **B. Edit the proposed name**
- **C. Place the wiki under an existing category** — when chosen, run
  `category-list` and let the user pick from the result

After resolving the root name, check whether it already exists at the top
level:

```
"$PY" "$CLIENT" category-list
```

If a top-level category with that name exists, **reuse it** (don't
duplicate) and tell the user. Otherwise, create it in Step 5.

## Step 3 — embedded prompt: outline the wiki

Now follow this embedded prompt, which adapts Andrej Karpathy's wiki
pattern for ERPEX. **Read it carefully and apply it from this step
onward.**

> You are building a **wiki as second memory** for the topic
> `$ARGUMENTS`. Follow the Karpathy wiki pattern, adapted for the ERPEX
> knowledge base.
>
> **Mental model.** A wiki is *not* a textbook. It is a graph of small,
> focused, interlinked pages. Each page covers ONE entity or ONE concept.
> Pages reference each other with Obsidian-style `[[Page Title]]`
> wikilinks; ERPEX auto-resolves these to real records on save. The
> reader navigates by clicking, not by scrolling.
>
> **Three layers** (mirrored as ERPEX subcategories under the chosen
> root):
> - **Entities** — concrete things: people, products, libraries,
>   datasets, organisations. Title Case, singular noun.
> - **Concepts** — abstract ideas: techniques, theories, patterns,
>   definitions. Title Case, noun phrase.
> - **Synthesis** — opinionated cross-cutting takes: comparisons,
>   debates, "how X relates to Y", historical arcs.
>
> **Article shape.** The body is **pure markdown** — no YAML frontmatter,
> no metadata block. Every metadata field has a structured home in ERPEX
> and is set via the API, not the body:
>
> | Metadata | Where it lives | How you set it |
> |---|---|---|
> | Tags | `erpex_tag_ids` | `--tag <name>` flags on `article-create` / `article-update` (one flag per tag) |
> | Author | `erpex_owner_id` | Auto-set to the API-key user — do nothing |
> | Created date | `create_date` | Auto-set by Odoo — do nothing |
> | Updated date | `write_date` + `erpex_last_content_update` | Auto-set on every write — do nothing |
> | Status | `erpex_status` | `--status draft` (or omit; defaults to `draft`) |
> | Source provenance | encoded as a tag with the prefix `source:` | `--tag source:llm-generated` on every wiki article |
>
> **Do not** write `tags:`, `created:`, `updated:`, `author:`, `status:`,
> or `sources:` anywhere in the body. ERPEX shows these on the article
> form already; duplicating them in body text drifts and pollutes the
> rendered markdown.
>
> Body content starts directly with H2 sections (e.g. `## Overview`,
> `## Why it matters`, `## See also`). Don't even write the title — it's
> the `name` field, not the body.
>
> **Word counts (guidance, not caps).** Entities ~150–400w. Concepts
> ~200–500w. Synthesis ~300–800w. The Index ~200–500w (mostly a list).
>
> **Linking rule (structural).** Every time you mention an entity or
> concept that has its own page in this wiki, link it as `[[Page
> Title]]`. Don't aim for a number — aim for completeness. Self-links
> are forbidden.
>
> **Naming.** Titles are Title Case (`Vector Embedding`, not `vector
> embedding` or `vector-embedding`). Wikilinks use the exact title.
>
> **Workflow:**
>
> 1. **Outline first.** Produce an outline before any API call:
>    - Root category name (already resolved in Step 2)
>    - Three subcategories: `Entities`, `Concepts`, `Synthesis` (always
>      these three)
>    - 5–15 leaf article titles distributed across those three subs
>      (skew toward Entities + Concepts; 1–3 Synthesis pieces is enough)
>    - Plus one `<Root> Index` article that lives directly under the
>      root (one-line links to every other page)
>    - For each leaf article, also plan **2–4 content tags** (lowercase,
>      kebab-case-OK) drawn from the topic — these will become real
>      `erpex_tag_ids` entries via `--tag` flags.
> 2. **Disambiguate.** Sample existing articles via
>    `article-list` (no `--category-id`) to detect title collisions. If a
>    planned title already exists in the DB, append ` (<Root>)` to
>    disambiguate.
> 3. **Confirm with the user.** Show the outline via AskUserQuestion
>    with options `Proceed`, `Edit outline`, `Cancel`. On `Edit`,
>    regenerate from feedback.
> 4. **Build the category tree.** `category-create` for the root (reuse
>    if it already exists, per Step 2), then `category-create
>    --parent-id <root>` for each of `Entities`, `Concepts`, `Synthesis`.
>    Store `sub_name → sub_id`.
> 5. **Pass 1 — register every title with real tags as a stub.** For
>    each outlined article (Index included):
>    ```
>    article-create --name "<Title>" --category-id <target> \
>        --body "Stub: pending body" --status draft \
>        --tag source:llm-generated --tag wiki:<root-slug> \
>        --tag <content-tag-1> [--tag <content-tag-2> ...]
>    ```
>    where `<root-slug>` is the root category name lowercased with
>    spaces → hyphens. The `source:` and `wiki:` tags are how we encode
>    provenance (no body frontmatter needed) — lint can later filter
>    `name like 'source:%'`. Capture `title → article_id`.
>
>    Why register titles first? `_sync_wikilinks` resolves `[[Title]]`
>    references by looking up real records at body-write time.
>    Registering all titles first guarantees Pass 2's links resolve
>    deterministically.
> 6. **Pass 2 — write real bodies.** For each non-Index article:
>    - Write the full body in **pure markdown** — no YAML, no metadata
>      block, no title line. Start directly with H2 sections.
>    - Embed `[[Title]]` references to OTHER articles in the same wiki
>      wherever they're mentioned.
>    - Save to `/tmp/erpex-wiki-<slug>.md`, then:
>      ```
>      article-update --article-id <id> --field body_file=/tmp/erpex-wiki-<slug>.md
>      ```
>    - Tags from Pass 1 stay; you don't need to re-pass them.
> 7. **Write the Index last.** Body = a markdown heading + a list, one
>    line per article, format `- [[Title]] — <≤120 char hook>`, grouped
>    by subcategory under H2 headings. No frontmatter.
> 8. **Lint pass (read-only).** After all writes, `article-get` each
>    article and surface:
>    - **Orphans** — articles whose `linked_article_ids` AND
>      `backlink_ids` are both empty (excluding the Index).
>    - **Dangling links** — `[[Title]]` references in bodies that
>      didn't resolve (compute by re-reading bodies and checking which
>      `[[…]]` tokens map to known titles in this wiki).
>    - **Ungrounded pages** — articles whose `tags` include
>      `source:llm-generated` and no other `source:*` tag. Flag as a
>      follow-up for a future `/ingest`.
> 9. **Print summary.** Root category ID + name, sub IDs, count of
>    articles, all `(article_id, title)` pairs, the lint findings, and
>    the reminder that everything is `draft` — promote to `published` in
>    the ERPEX UI when reviewed.

## Step 4 — execute

Walk the embedded workflow above end-to-end. Use the client commands
exactly as laid out in Steps 4–8 of the embedded prompt.

## Step 5 — final summary

End with:

- Root category ID + name
- Subcategory IDs (`Entities`, `Concepts`, `Synthesis`)
- Total article count
- A bulleted list of `(article_id, title)` pairs
- The lint findings (orphans / dangling links / ungrounded pages)
- Reminder: everything is `draft`. Review and promote to `published` from
  the ERPEX Knowledge Base UI.
