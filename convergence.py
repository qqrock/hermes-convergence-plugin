"""Hermes-native port of pi-extension-convergence.

The upstream Pi extension steers an agent after independent validations pass.
Hermes exposes a transform_tool_result hook rather than Pi's sendUserMessage API,
so the nudge is appended to the successful tool result that the model sees.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Optional


SOURCE_TOOLS = {"apply_patch", "edit", "patch", "str_replace", "write", "write_file"}
TERMINAL_TOOLS = {"terminal"}
FAILURE_MARKERS = re.compile(
    r"(?:\bfailed\b|\bfailure\b|\btraceback\b|\bexception\b|"
    r"\berror(?:\s+[a-z]+)?\s*[:=]|command failed|exit code\s*[1-9])",
    re.IGNORECASE,
)


@dataclass
class SessionState:
    source_revision: int = 0
    steered: bool = False
    passed_families: set[str] = field(default_factory=set)
    fingerprint_counts: dict[str, int] = field(default_factory=dict)

    def reset_for_source_change(self) -> None:
        self.source_revision += 1
        self.steered = False
        self.passed_families.clear()
        self.fingerprint_counts.clear()


_states: dict[str, SessionState] = {}
_lock = threading.RLock()


def _session_key(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("session_id") or kwargs.get("task_id") or "default")


def _state(kwargs: dict[str, Any]) -> SessionState:
    key = _session_key(kwargs)
    with _lock:
        return _states.setdefault(key, SessionState())


def _command(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    value = args.get("command") or args.get("cmd") or ""
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value)


def _classify(command: str) -> Optional[str]:
    cmd = " ".join(command.lower().split())
    if not cmd:
        return None
    if re.search(r"(?:^|[;&|]\s*)(?:pytest|python(?:\.exe)?\s+-m\s+(?:pytest|unittest)|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test|node\s+--test)\b", cmd):
        return "test"
    if re.search(r"(?:^|[;&|]\s*)(?:npm|pnpm|yarn)\s+run\s+build\b|(?:^|[;&|]\s*)(?:npx\s+)?tsc\b|(?:^|[;&|]\s*)cargo\s+(?:build|check)\b", cmd):
        return "build"
    if (
        re.search(r"\b(?:curl(?:\.exe)?|invoke-restmethod|irm)\b", cmd)
        and re.search(r"https?://[^\s'\"]+/(?:api|v1)(?:/|\b)", cmd)
        and not re.search(r"/health(?:\b|/)", cmd)
    ):
        return "runtime"
    return None


def _result_parts(result: Any) -> tuple[str, Optional[int]]:
    if isinstance(result, str):
        text = result
        try:
            parsed = json.loads(result)
        except (TypeError, ValueError):
            return text, None
        if isinstance(parsed, dict):
            output = parsed.get("output")
            error = parsed.get("error")
            combined = "\n".join(str(v) for v in (output, error) if v not in (None, ""))
            exit_code = parsed.get("exit_code")
            return combined or text, exit_code if isinstance(exit_code, int) else None
        return text, None
    if isinstance(result, dict):
        output = result.get("output")
        error = result.get("error")
        combined = "\n".join(str(v) for v in (output, error) if v not in (None, ""))
        exit_code = result.get("exit_code")
        return combined or json.dumps(result, ensure_ascii=False), exit_code if isinstance(exit_code, int) else None
    return str(result), None


def _passed(status: Any, result: Any) -> bool:
    text, exit_code = _result_parts(result)
    if str(status or "ok").lower() not in {"ok", "success", "completed"}:
        return False
    if exit_code not in (None, 0):
        return False
    return not FAILURE_MARKERS.search(text)


def _fingerprint(family: str, command: str, revision: int) -> str:
    normalized = " ".join(command.lower().split())
    return f"{revision}:{family}:{normalized}"


def on_source_tool(tool_name: str = "", **kwargs: Any) -> None:
    if str(tool_name).lower() not in SOURCE_TOOLS:
        return
    with _lock:
        _state(kwargs).reset_for_source_change()


def transform_tool_result(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    status: Any = None,
    **kwargs: Any,
) -> Optional[str]:
    if str(tool_name).lower() not in TERMINAL_TOOLS:
        return None
    command = _command(args)
    family = _classify(command)
    if family is None or not _passed(status, result):
        return None

    original = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    with _lock:
        state = _state(kwargs)
        if state.steered:
            return None
        state.passed_families.add(family)
        fingerprint = _fingerprint(family, command, state.source_revision)
        state.fingerprint_counts[fingerprint] = state.fingerprint_counts.get(fingerprint, 0) + 1
        strong = {"test", "runtime"}.issubset(state.passed_families)
        repetitive = family == "test" and state.fingerprint_counts[fingerprint] >= 3
        if not (strong or repetitive):
            return None
        state.steered = True

    reason = (
        "自动化测试与真实业务 API 验证均已通过"
        if strong
        else "同一项验证在没有修改源码的情况下已连续通过三次"
    )
    nudge = (
        "\n\n[Convergence / 收敛提醒]\n"
        f"{reason}。不要再次运行已经通过的同类检查。请对照用户要求确认是否还有未完成项；"
        "若没有，立即总结结果、验证证据与剩余风险并结束任务。只有出现新修改或新的具体失败证据时才继续调用工具。"
    )
    return original + nudge


def on_session_end(**kwargs: Any) -> None:
    key = _session_key(kwargs)
    with _lock:
        _states.pop(key, None)
