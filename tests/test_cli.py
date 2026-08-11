import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from epistates.__main__ import main


FIXTURES = Path(__file__).parent.parent / "fixtures"


class CliValidationTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_audit_requires_task_card(self):
        code, output = self.call("validate", str(FIXTURES / "audit-result-valid.json"))
        self.assertEqual(code, 1)
        self.assertIn("requiere --task-card", output)

    def test_audit_with_exact_task_card_is_valid(self):
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
        )
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_task_rejects_audit_binding_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)

    def test_audit_rejects_wrong_expected_run(self):
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-999", "--attempt-id", "attempt-001",
        )
        self.assertEqual(code, 1)
        self.assertIn("run_id no coincide", output)

    def test_duplicate_json_keys_fail_closed(self):
        code, output = self.call("validate", str(FIXTURES / "artifact-duplicate-schema.json"))
        self.assertEqual(code, 1)
        self.assertIn("clave JSON duplicada", output)

    def test_adapter_capabilities_valid(self):
        code, output = self.call("validate", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"))
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_adapter_capabilities_bad_is_invalid(self):
        code, output = self.call("validate", str(FIXTURES / "adapter-capabilities-bad-capability.json"))
        self.assertEqual(code, 1)
        self.assertIn("INVALID", output)

    def test_preflight_result_requires_full_binding(self):
        code, output = self.call("validate", str(FIXTURES / "preflight-result-ok.json"))
        self.assertEqual(code, 1)
        self.assertIn("preflight-result requiere", output)

    def test_preflight_result_ok_binds_valid(self):
        code, output = self.call(
            "validate", str(FIXTURES / "preflight-result-ok.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode", "--expected-command", "idle",
        )
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_preflight_result_blocked_binds_valid(self):
        code, output = self.call(
            "validate", str(FIXTURES / "preflight-result-blocked.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode", "--expected-command", "idle",
        )
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_preflight_result_wrong_session_is_invalid(self):
        code, output = self.call(
            "validate", str(FIXTURES / "preflight-result-ok.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "wrong", "--expected-command", "idle",
        )
        self.assertEqual(code, 1)
        self.assertIn("outcome", output)

    def test_adapter_rejects_binding_options(self):
        code, output = self.call(
            "validate", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)
