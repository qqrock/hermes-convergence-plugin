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

    def call(self, command, result='{"output":"ok","exit_code":0,"error":null}', session="s1"):
        return MODULE.transform_tool_result(
            tool_name="terminal", args={"command": command}, result=result,
            status="ok", session_id=session,
        )

    def test_test_and_business_runtime_trigger_once(self):
        self.assertIsNone(self.call("pytest -q"))
        changed = self.call("curl http://localhost:8080/api/items")
        self.assertIsNotNone(changed)
        self.assertIn("收敛提醒", changed)
        self.assertIsNone(self.call("pytest -q"))

    def test_three_identical_passes_trigger(self):
        self.assertIsNone(self.call("pytest -q"))
        self.assertIsNone(self.call("pytest -q"))
        self.assertIn("收敛提醒", self.call("pytest -q"))

    def test_source_edit_resets_evidence(self):
        self.assertIsNone(self.call("pytest -q"))
        MODULE.on_source_tool(tool_name="write_file", session_id="s1")
        self.assertIsNone(self.call("curl http://localhost:8080/api/items"))

    def test_failed_command_is_not_evidence(self):
        failed = '{"output":"1 failed","exit_code":1,"error":null}'
        for _ in range(4):
            self.assertIsNone(self.call("pytest -q", failed))

    def test_health_probe_is_excluded_but_api_probe_counts(self):
        self.assertIsNone(self.call("curl http://localhost:8080/health"))
        self.assertIsNone(self.call("curl http://localhost:8080/api/items"))
        self.assertIn("收敛提醒", self.call("pytest -q"))

    def test_build_plus_test_is_not_a_strong_oracle(self):
        self.assertIsNone(self.call("npm run build"))
        self.assertIsNone(self.call("pytest -q"))

    def test_session_state_is_isolated(self):
        self.assertIsNone(self.call("pytest -q", session="a"))
        self.assertIsNone(self.call("curl http://localhost/api/items", session="b"))


if __name__ == "__main__":
    unittest.main()
