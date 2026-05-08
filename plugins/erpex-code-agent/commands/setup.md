---
description: Configure ERPEX URL, API key, rewrite-subagent model, and TLS trust. Run once per machine.
argument-hint: "[erpex_url] [api_key] [model] [insecure]"
allowed-tools: ["Bash"]
---

Positional arguments:

- `$1` — ERPEX base URL (e.g. `https://erpex.example.com`)
- `$2` — bearer API key from your ERPEX user profile (Preferences → Account Security)
- `$3` — model the `erpex-rewriter` subagent should use (default `sonnet`)
- `$4` — pass the literal word `insecure` if your ERPEX host has an
  incomplete TLS chain (e.g. `bts.erpex.ai` is known to omit Sectigo's
  intermediate cert). Sets `verify_ssl = "false"` in the config so urllib
  doesn't reject the chain. Omit for normal hosts.

If `$1` or `$2` is missing, abort with:
`/setup https://erpex.example.com sk_xxx sonnet [insecure]`

Build the helper invocation, appending `--insecure` only if `$4` is exactly
`insecure` (case-insensitive):

```
INSECURE_FLAG=""
if [ "$(echo "$4" | tr '[:upper:]' '[:lower:]')" = "insecure" ]; then
  INSECURE_FLAG="--insecure"
fi
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" setup \
  --url "$1" --api-key "$2" --model "${3:-sonnet}" $INSECURE_FLAG
```

After it succeeds, confirm to the user:
- Config written to `~/.config/erpex-code-agent/plugin.toml` (mode 0600).
- TLS verification is `enabled` (or `disabled` if `insecure` was passed).
- Hooks are active: every prompt/reply syncs to a task in ERPEX,
  auto-creating the project (folder name) and task (first prompt) if needed.

If hooks misbehave, suggest:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/erpex_agentic_client.py" doctor
tail -f ~/.cache/erpex-code-agent/hook.log
```

Next: just start chatting, or run `/rewrite` to polish the BR.
