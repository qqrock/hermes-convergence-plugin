# Hermes Convergence Plugin

A native [Hermes Agent](https://github.com/NousResearch/hermes-agent) port of
[pi-extension-convergence](https://github.com/yang2020chen/pi-extension-convergence).
It helps local and heavily quantized models stop repetitive validation loops
without hard-stopping the agent.

## Why

Some capable local models finish the implementation correctly but keep reading
files and re-running passing checks until the step budget expires. This plugin
adds a one-time, model-visible convergence reminder only when evidence is strong
enough.

## Completion oracle

Strong steering requires both:

1. an automated test command passed; and
2. a real `/api/` or `/v1/` business endpoint probe passed.

The plugin deliberately excludes `/health`, file inspection, grep, database
schema inspection, and build success as sufficient completion evidence. It also
emits a softer reminder when the exact same test passes three times without a
source edit. Any source-edit tool clears all prior evidence.

## Install

```powershell
git clone https://github.com/qqrock/hermes-convergence-plugin `
  "$env:LOCALAPPDATA\hermes\plugins\convergence"
hermes plugins enable convergence
hermes plugins doctor convergence
```

Restart Hermes or start a new session after enabling the plugin.

## Verify

```powershell
$python = "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe"
& $python -m unittest discover -s tests -p "test_*.py" -v
hermes plugins validate .
```

## Design

- Hermes hooks: `pre_tool_call`, `transform_tool_result`, `on_session_end`
- Per-session, thread-safe state
- No external Python dependencies
- Steering only; never blocks or kills the agent

## Attribution

This project is a Hermes-native derivative of Yang Chen's MIT-licensed
`pi-extension-convergence`. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).

The Completion Oracle rules were informed by the accompanying
[Bonsai 27B convergence steering guide](https://blog.757688.xyz/bonsai-27b-agent-convergence-steering-guide/).
