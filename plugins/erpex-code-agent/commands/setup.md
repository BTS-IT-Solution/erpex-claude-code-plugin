---
description: Configure ERPEX URL, API key, and rewrite-subagent model. Run once per machine.
argument-hint: "[erpex_url] [api_key] [model]"
allowed-tools: ["Bash"]
---

Run the setup helper with the three positional arguments:

- `$1` — ERPEX base URL (e.g. `https://erpex.example.com`)
- `$2` — bearer API key from your ERPEX user profile (Preferences → Account Security)
- `$3` — model the `erpex-rewriter` subagent should use (default `sonnet`)

If any argument is missing, abort and tell the user the correct invocation:
`/setup https://erpex.example.com sk_xxx sonnet`

Then run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" setup --url "$1" --api-key "$2" --model "${3:-sonnet}"
```

After it succeeds, confirm to the user:
- Config written to `~/.config/erpex-code-agent/plugin.toml` (mode 0600).
- The rewrite subagent will use the model they specified.
- Hooks are now active: every prompt/reply syncs to a task in ERPEX,
  auto-creating the project (folder name) and task (first prompt) if needed.
- Next: just start chatting, or run `/rewrite` to polish the BR.
