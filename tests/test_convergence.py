import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "convergence.py"
SPEC = importlib.util.spec_from_file_location("convergence_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ConvergenceTests(unittest.TestCase):
    def setUp(self):
        MODULE._states.clear()

    def call(self, command, output="1 passed in 0.01s", session="s1", exit_code=0):
        result = {"output": output, "exit_code": exit_code, "error": None}
        return MODULE.transform_tool_result(
            tool_name="terminal", args={"command": command}, result=result,
            status="ok", session_id=session,
        )

    def test_upstream_test_fingerprints(self):
        self.assertEqual(MODULE.classify_check("pytest tests/test_api.py -q").fingerprint, "pytest:tests/test_api.py")
        self.assertEqual(MODULE.classify_check("node --test dist/tests/user.test.js").fingerprint, "npm_test:dist/tests/user.test.js")

    def test_positive_pass_marker_is_required(self):
        self.assertIsNone(self.call("pytest -q", output="completed with exit code zero"))
        self.assertIsNone(self.call("pytest -q", output="1 failed, 5 passed", exit_code=0))

    def test_two_upstream_families_trigger_strong_steer(self):
        self.assertIsNone(self.call("pytest -q"))
        changed = self.call("curl -i http://localhost:8080/api/items", output='HTTP/1.1 200 OK\n{"items":[]}')
        self.assertIn(MODULE.STRONG_STEER_TEXT, changed)

    def test_build_plus_test_matches_upstream_multi_family_rule(self):
        self.assertIsNone(self.call("npm run build", output="build succeeded"))
        changed = self.call("pytest -q")
        self.assertIn(MODULE.STRONG_STEER_TEXT, changed)

    def test_three_same_test_passes_trigger_soft_steer(self):
        self.assertIsNone(self.call("pytest tests/test_api.py -q"))
        self.assertIsNone(self.call("pytest tests/test_api.py -q"))
        changed = self.call("pytest tests/test_api.py -q")
        self.assertIn(MODULE.SOFT_STEER_TEXT, changed)

    def test_different_checks_do_not_count_as_consecutive_upstream_repeats(self):
        self.assertIsNone(self.call("pytest tests/test_a.py -q"))
        self.assertIsNone(self.call("pytest tests/test_b.py -q"))
        self.assertIsNone(self.call("pytest tests/test_c.py -q"))

    def test_health_is_excluded(self):
        self.assertIsNone(MODULE.classify_check("curl http://localhost:8080/health"))

    def test_source_edit_clears_evidence_and_unlocks(self):
        self.call("pytest -q")
        self.call("curl -i http://localhost/api/items", output="HTTP/1.1 200 OK")
        MODULE.on_source_tool(tool_name="write_file", session_id="s1")
        state = MODULE._states["s1"]
        self.assertFalse(state.steered)
        self.assertEqual(state.passed_families, set())

    def test_sessions_are_isolated_hermes_extension(self):
        self.call("pytest -q", session="a")
        self.call("curl -i http://localhost/api/items", output="HTTP/1.1 200 OK", session="b")
        self.assertEqual(MODULE._states["a"].passed_families, {"test"})
        self.assertEqual(MODULE._states["b"].passed_families, {"runtime"})

    def test_completion_policy_is_loaded(self):
        self.assertIn("TASK COMPLETION POLICY", MODULE.completion_policy()["context"])

    def test_path_failure_repeats_authoritative_written_path(self):
        MODULE.on_source_tool(tool_name="write_file", session_id="s1")
        MODULE.transform_tool_result(
            tool_name="write_file", args={"path": r"C:\Users\rock\Desktop\pelican-motorcycle.html"},
            result='{"message":"written"}', status="ok", session_id="s1",
        )
        changed = MODULE.transform_tool_result(
            tool_name="read_file", args={"path": r"C:\Users\rock\Desktop\pel..."},
            result='{"error":"File not found"}', status="error", session_id="s1",
        )
        self.assertIn(r"C:\Users\rock\Desktop\pelican-motorcycle.html", changed)

    def test_two_successful_artifact_checks_trigger_delivery(self):
        MODULE.on_source_tool(tool_name="write_file", session_id="s1")
        MODULE.transform_tool_result(
            tool_name="write_file", args={"path": "artifact.html"},
            result='{"message":"written"}', status="ok", session_id="s1",
        )
        self.assertIsNone(MODULE.transform_tool_result(
            tool_name="read_file", args={"path": "artifact.html"},
            result='{"content":"<html></html>"}', status="ok", session_id="s1",
        ))
        changed = MODULE.transform_tool_result(
            tool_name="browser_navigate", args={"url": "file:///artifact.html"},
            result='{"title":"artifact"}', status="ok", session_id="s1",
        )
        self.assertIn(MODULE.ARTIFACT_STEER_TEXT, changed)

    def test_static_quality_gate_detects_real_svg_css_failures(self):
        content = """<!doctype html><html><body><svg xmlns="http://www.w3.org/2000/svg">
        <style>
        #wheelBack,#wheelFront{animation:spin 1s linear infinite}
        @keyframes wingFlap{0%,100%{-14deg}50%{16deg}}
        @keyframes wingUp{0%,100%-14deg}
        </style>
        <g id="wheelBack"><circle r="20"/></g><g id="wheelFront"><circle r="20"/></g>
        </svg></body></html>"""
        issues = MODULE.quality_issues_for_artifact("artifact.html", content)
        joined = "\n".join(issues)
        self.assertIn("Invalid keyframe body", joined)
        self.assertIn("Malformed @keyframes", joined)
        self.assertIn("#wheelBack", joined)
        self.assertIn("transform-origin", joined)

    def test_clean_html_svg_passes_static_gate(self):
        content = """<!doctype html><html><body><svg xmlns="http://www.w3.org/2000/svg">
        <style>
        #wheel{transform-box:fill-box;transform-origin:center;animation:spin 1s linear infinite}
        @keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
        </style><g id="wheel"><circle r="20"/></g></svg></body></html>"""
        self.assertEqual(MODULE.quality_issues_for_artifact("artifact.html", content), [])

    def test_successful_write_surfaces_static_quality_issues(self):
        MODULE.on_source_tool(tool_name="write_file", args={}, session_id="s1")
        changed = MODULE.transform_tool_result(
            tool_name="write_file",
            args={
                "path": "artifact.html",
                "content": "<html><body><svg xmlns='http://www.w3.org/2000/svg'><style>"
                           "@keyframes bad{0%{-8deg}}"
                           "</style></svg></body></html>",
            },
            result='{"message":"written"}', status="ok", session_id="s1",
        )
        self.assertIn("static quality gate", changed)
        self.assertTrue(MODULE._states["s1"].quality_issues)

    def test_pre_tool_blocks_guessed_read_path(self):
        MODULE.on_source_tool(tool_name="write_file", args={}, session_id="s1")
        MODULE.transform_tool_result(
            tool_name="write_file", args={"path": r"C:\Users\rock\Desktop\artifact.html"},
            result='{"message":"written"}', status="ok", session_id="s1",
        )
        directive = MODULE.on_source_tool(
            tool_name="read_file", args={"path": r"C:\Users\rock\Desktop\art..."}, session_id="s1",
        )
        self.assertEqual(directive["action"], "block")
        self.assertIn(r"C:\Users\rock\Desktop\artifact.html", directive["message"])

    def test_pre_tool_blocks_third_artifact_verification(self):
        MODULE.on_source_tool(tool_name="write_file", args={}, session_id="s1")
        MODULE.transform_tool_result(
            tool_name="write_file", args={"path": "artifact.html", "content": "<html><body></body></html>"},
            result='{"message":"written"}', status="ok", session_id="s1",
        )
        MODULE.transform_tool_result(
            tool_name="read_file", args={"path": "artifact.html"},
            result='{"content":"ok"}', status="ok", session_id="s1",
        )
        MODULE.transform_tool_result(
            tool_name="browser_navigate", args={"url": "file:///artifact.html"},
            result='{"title":"artifact"}', status="ok", session_id="s1",
        )
        directive = MODULE.on_source_tool(
            tool_name="browser_snapshot", args={}, session_id="s1",
        )
        self.assertEqual(directive["action"], "block")
        self.assertIn("already passed", directive["message"])

    def test_clean_static_gate_leaves_only_one_visual_check(self):
        MODULE.on_source_tool(tool_name="write_file", args={}, session_id="s1")
        MODULE.transform_tool_result(
            tool_name="write_file", args={"path": "artifact.html", "content": "<html><body></body></html>"},
            result='{"message":"written"}', status="ok", session_id="s1",
        )
        changed = MODULE.transform_tool_result(
            tool_name="browser_navigate", args={"url": "file:///artifact.html"},
            result='{"title":"artifact"}', status="ok", session_id="s1",
        )
        self.assertIn(MODULE.ARTIFACT_STEER_TEXT, changed)


if __name__ == "__main__":
    unittest.main()
