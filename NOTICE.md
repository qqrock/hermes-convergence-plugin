# Attribution notice

This repository ports the core convergence-state concept from
[yang2020chen/pi-extension-convergence](https://github.com/yang2020chen/pi-extension-convergence)
from Pi's TypeScript extension API to Hermes Agent's native Python plugin API.

Original work copyright (c) 2026 yang2020chen, licensed under MIT.

The Hermes port changes the integration surface, maintains isolated state per
session, uses `transform_tool_result` for steering, and implements a conservative
Completion Oracle requiring automated tests plus a business API probe.
