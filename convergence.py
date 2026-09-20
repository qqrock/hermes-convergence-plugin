"""Faithful Hermes port of pi-extension-convergence v1.0.

The state machine, check classification, positive PASS markers, fingerprints,
and two-tier steering mirror the upstream TypeScript implementation. Only the
host integration and state ownership differ: Hermes uses plugin hooks and this
port isolates state per session.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger("hermes_plugins.convergence")

SOURCE_TOOLS = {"edit", "write", "apply_patch", "patch", "str_replace", "write_file"}
TERMINAL_TOOLS = {"terminal"}
ARTIFACT_VERIFICATION_TOOLS = {
    "read_file", "terminal", "browser", "browser_navigate", "browser_open",
    "browser_snapshot", "browser_vision",
}

STRONG_STEER_TEXT = (
    "The required validation has already passed and no source code has changed since then. "
    "Do not perform additional verification. Review the explicit task requirements once, "
    "provide the final result, and end the task."
)
SOFT_STEER_TEXT = (
    "You have repeated the same successful validation without source changes. "
    "Do not run the same check again. If all explicit requirements are satisfied, "
    "finish the task now. Otherwise continue only with the remaining unmet requirements."
)
ARTIFACT_STEER_TEXT = (
    "The requested artifact was written successfully and has already received sufficient verification. "
    "Do not rewrite it or start another validation method without a concrete observed defect. "
    "Report the exact saved path and finish the task now."
)


@dataclass(frozen=True)
class Check:
    family: str
    fingerprint: str


@dataclass
class SessionState:
    source_revision: int = 0
    steered: bool = False
    passed_families: set[str] = field(default_factory=set)
    fingerprint_counts: dict[str, int] = field(default_factory=dict)
    consecutive_pass_count: int = 0
    last_passed_fingerprint: Optional[str] = None
    last_written_path: Optional[str] = None
    artifact_verification_count: int = 0
    artifact_path_failures: int = 0
    artifact_steered: bool = False

    def reset_verification(self) -> None:
        self.passed_families.clear()
        self.fingerprint_counts.clear()
        self.consecutive_pass_count = 0
        self.last_passed_fingerprint = None
        self.last_written_path = None
        self.artifact_verification_count = 0
        self.artifact_path_failures = 0
        self.artifact_steered = False


_states: dict[str, SessionState] = {}
_lock = threading.RLock()


def _session_key(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("session_id") or kwargs.get("task_id") or "default")


def _state(kwargs: dict[str, Any]) -> SessionState:
    key = _session_key(kwargs)
    return _states.setdefault(key, SessionState())


def _command(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    value = args.get("command") or args.get("cmd") or ""
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value)


def classify_check(command: str) -> Optional[Check]:
    """Mirror upstream classifyCheck(), accepting Windows path separators too."""
    lowered = command.lower()

    if "pytest" in lowered or "python -m pytest" in lowered or "python -m unittest" in lowered:
        match = re.search(r"tests[\\/][a-zA-Z0-9_\-.]+", command, re.IGNORECASE)
        target = match.group(0).replace("\\", "/") if match else "all"
        return Check("test", f"pytest:{target}")

    if "npm test" in lowered or "npm run test" in lowered or "node --test" in lowered:
        match = re.search(r"dist[\\/]tests[\\/][a-zA-Z0-9_\-.]+", command, re.IGNORECASE)
        if match is None:
            match = re.search(r"tests[\\/][a-zA-Z0-9_\-.]+", command, re.IGNORECASE)
        target = match.group(0).replace("\\", "/") if match else "default"
        return Check("test", f"npm_test:{target}")

    if "npm run build" in lowered or "tsc " in lowered or lowered.endswith("tsc"):
        return Check("build", "build:tsc")

    if "curl" in lowered:
        if "/health" in lowered and "/api/" not in lowered:
            return None
        match = re.search(r"(/api/[a-zA-Z0-9_\-/]+)", command, re.IGNORECASE)
        if match:
            return Check("runtime", f"curl:{match.group(1)}")
        match = re.search(r"https?://[^\s/]+(/api/[^\s?\"']*)", command, re.IGNORECASE)
        if match:
            return Check("runtime", f"curl:{match.group(1)}")

    return None


def _result_text(result: Any) -> str:
    """Extract Hermes terminal output, equivalent to Pi's text-content join."""
    if isinstance(result, dict):
        return str(result.get("output") or "")
    if not isinstance(result, str):
        return str(result)
    try:
        parsed = json.loads(result)
    except (TypeError, ValueError):
        return result
    if isinstance(parsed, dict):
        output = parsed.get("output")
        error = parsed.get("error")
        return "\n".join(str(value) for value in (output, error) if value not in (None, ""))
    return result


def _exit_succeeded(status: Any, result: Any) -> bool:
    if str(status or "ok").lower() not in {"ok", "success", "completed"}:
        return False
    parsed = result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (TypeError, ValueError):
            return True
    if isinstance(parsed, dict):
        exit_code = parsed.get("exit_code")
        if isinstance(exit_code, int) and exit_code != 0:
            return False
    return True


def _tool_succeeded(status: Any, result: Any) -> bool:
    if not _exit_succeeded(status, result):
        return False
    parsed = result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (TypeError, ValueError):
            return True
    return not (isinstance(parsed, dict) and parsed.get("error"))


def _source_path(args: Any) -> Optional[str]:
    if not isinstance(args, dict):
        return None
    for key in ("path", "file_path", "filename"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_path_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in (
        "file not found", "filenotfounderror", "no such file or directory",
        "cannot read", "not a regular file", "path was being truncated",
    ))


def _artifact_guidance(state: SessionState, tool_name: str, args: Any, result: Any, status: Any) -> Optional[str]:
    """Hermes-specific guard against post-write path and validation loops."""
    original = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

    if tool_name in SOURCE_TOOLS:
        if _tool_succeeded(status, result):
            path = _source_path(args)
            if path:
                state.last_written_path = path
                logger.info("Artifact write succeeded at %s", path)
        return None

    if state.last_written_path is None or tool_name not in ARTIFACT_VERIFICATION_TOOLS:
        return None

    text = _result_text(result)
    if not _tool_succeeded(status, result):
        if _is_path_failure(text):
            state.artifact_path_failures += 1
            logger.info("Post-write path verification failed count=%s", state.artifact_path_failures)
            return (
                original
                + "\n\n[Convergence / exact-path reminder]\n"
                + f"The artifact was already written successfully at this exact path: {state.last_written_path}. "
                + "Do not guess, abbreviate, translate, or reconstruct the path. Reuse that exact path at most once. "
                + "If no concrete defect in the artifact has been observed, stop validating and deliver the saved file."
            )
        return None

    state.artifact_verification_count += 1
    logger.info("Post-write artifact verification count=%s", state.artifact_verification_count)
    if state.artifact_verification_count >= 2 and not state.artifact_steered:
        state.artifact_steered = True
        return original + "\n\n[Convergence / artifact delivery]\n" + ARTIFACT_STEER_TEXT
    return None


def looks_passed(text: str, family: str) -> bool:
    """Faithful port of upstream looksPassed()."""
    lowered = text.lower()

    if (
        "error:" in lowered
        or "err_assertion" in lowered
        or "assertionerror" in lowered
        or "failed" in lowered
        or "fail 1" in lowered
        or "fail 2" in lowered
        or "not ok " in lowered
        or ("403 forbidden" in lowered and "200 ok" not in lowered)
        or "500 internal" in lowered
        or "404 not found" in lowered
    ):
        return False

    if family == "test":
        return bool(
            re.search(r"\b\d+\s+passed\b", lowered)
            or "✔" in text
            or "ℹ pass" in lowered
            or re.search(r"\bpass\b", lowered)
            or "passed in" in lowered
        )

    if family == "build":
        return "build succeeded" in lowered or "build success" in lowered or "error ts" not in lowered

    if family == "runtime":
        return bool(
            "200 ok" in lowered
            or "http/1.1 200" in lowered
            or "http/1.0 200" in lowered
            or '"status":"ok"' in lowered
            or '"status": "ok"' in lowered
            or "id,status,customer,created_at" in lowered
            or '"items":' in lowered
            or re.search(r"\b200\b", lowered)
        )

    return False


def on_source_tool(tool_name: str = "", **kwargs: Any) -> None:
    if str(tool_name).lower() not in SOURCE_TOOLS:
        return
    with _lock:
        state = _state(kwargs)
        state.source_revision += 1
        state.reset_verification()
        was_steered = state.steered
        state.steered = False
        if was_steered:
            logger.info("Source modified after steer (revision %s); steering unlocked", state.source_revision)
        else:
            logger.info("Source modified (revision %s); prior evidence reset", state.source_revision)


def transform_tool_result(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    status: Any = None,
    **kwargs: Any,
) -> Optional[str]:
    normalized_tool = str(tool_name).lower()
    with _lock:
        state = _state(kwargs)
        artifact_result = _artifact_guidance(state, normalized_tool, args, result, status)
    if artifact_result is not None:
        return artifact_result

    if normalized_tool not in TERMINAL_TOOLS or not _exit_succeeded(status, result):
        return None
    check = classify_check(_command(args))
    if check is None:
        return None
    text = _result_text(result)
    if not looks_passed(text, check.family):
        return None

    original = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    with _lock:
        state = _state(kwargs)
        state.passed_families.add(check.family)
        current_count = state.fingerprint_counts.get(check.fingerprint, 0) + 1
        state.fingerprint_counts[check.fingerprint] = current_count

        if state.last_passed_fingerprint == check.fingerprint:
            state.consecutive_pass_count += 1
        else:
            state.consecutive_pass_count = 1
            state.last_passed_fingerprint = check.fingerprint

        logger.info(
            "PASS family=%s fingerprint=%s families=%s repeat=%s consecutive=%s",
            check.family, check.fingerprint, sorted(state.passed_families),
            current_count, state.consecutive_pass_count,
        )
        if state.steered:
            return None

        if len(state.passed_families) >= 2:
            state.steered = True
            logger.info("Strong multi-evidence reached; triggering strong steer")
            return original + "\n\n[Convergence Notice]\n" + STRONG_STEER_TEXT

        if current_count >= 3 or state.consecutive_pass_count >= 3:
            state.steered = True
            logger.info("Repeat-check threshold reached; triggering soft steer")
            return original + "\n\n[Convergence Notice]\n" + SOFT_STEER_TEXT

    return None


def completion_policy(**_: Any) -> dict[str, str]:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "convergence.md"
    try:
        policy = prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("Completion policy is unavailable: %s", prompt_path)
        return {}
    return {"context": policy}


def on_session_end(**kwargs: Any) -> None:
    with _lock:
        _states.pop(_session_key(kwargs), None)
