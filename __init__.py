"""Convergence — stop repetitive validation loops after sufficient evidence."""

import sys
from pathlib import Path

_PLUGIN_DIR = str(Path(__file__).resolve().parent)
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from convergence import completion_policy, on_session_end, on_source_tool, transform_tool_result


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", on_source_tool)
    ctx.register_hook("transform_tool_result", transform_tool_result)
    ctx.register_hook("pre_llm_call", completion_policy)
    ctx.register_hook("on_session_end", on_session_end)
