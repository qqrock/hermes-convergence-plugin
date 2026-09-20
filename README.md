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

The runtime behavior now mirrors the upstream v1.0 implementation:

1. checks are classified as test, build, or business-runtime evidence;
2. output must contain the same positive PASS markers used upstream;
3. two distinct passing evidence families trigger strong steering;
4. three repeated or consecutive passing checks trigger soft steering;
5. any source edit clears evidence and unlocks steering.

The plugin deliberately excludes `/health`, file inspection, grep, and database
schema inspection. As in upstream v1.0, build is an evidence family and can pair
with tests for the two-family threshold. Hermes-specific additions are per-session
state isolation, thread safety, Windows path handling, and automatic injection of
the bundled Completion Policy.

For single-file artifacts, the Hermes layer remembers the exact successful write
path, blocks path-guessing loops, and asks the model to deliver after two successful
post-write checks unless a concrete defect was observed. Version 1.3 adds a fast,
dependency-free static quality gate for JSON and HTML/SVG/CSS. It catches malformed
JSON/XML, missing HTML closing tags, invalid degree-only keyframe bodies, malformed
keyframe selectors, and animated SVG groups whose transform origin would make them
rotate out of place.

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

- Hermes hooks: `pre_tool_call`, `transform_tool_result`, `pre_llm_call`, `on_session_end`
- Per-session, thread-safe state
- No external Python dependencies
- Upstream-compatible classification, fingerprints, PASS markers, counters, and steering text
- Blocks only a mismatched post-write read path or verification beyond the completed
  artifact budget; normal creation, correction, and task tools remain available

## Attribution

This project is a Hermes-native derivative of Yang Chen's MIT-licensed
`pi-extension-convergence`. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).

The Completion Oracle rules were informed by the accompanying
[Bonsai 27B convergence steering guide](https://blog.757688.xyz/bonsai-27b-agent-convergence-steering-guide/).
