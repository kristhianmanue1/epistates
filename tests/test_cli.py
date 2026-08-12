import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from epistates.__main__ import main
from epistates.contracts import ValidationError
from epistates.dispatch import _MESSAGE_MAX_BYTES


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
        self.assertIn("audit-result requiere", output)
        self.assertIn("--task-card", output)

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

def _dispatch_receipt_args():
    return [
        "validate", str(FIXTURES / "dispatch-receipt-ok.json"),
        "--task-card", str(FIXTURES / "task-card-valid.json"),
        "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
        "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
        "--run-id", "run-001", "--attempt-id", "attempt-001",
        "--expected-session-name", "epistates-opencode",
        "--expected-command", "idle",
        "--max-preflight-age-seconds", "600",
        "--message-file", str(FIXTURES / "dispatch-message.txt"),
    ]


class CliDispatchReceiptTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_dispatch_receipt_requires_full_binding(self):
        code, output = self.call("validate", str(FIXTURES / "dispatch-receipt-ok.json"))
        self.assertEqual(code, 1)
        self.assertIn("dispatch-receipt requiere", output)
        for option in ("--preflight-result", "--expected-command",
                       "--max-preflight-age-seconds", "--message-file"):
            self.assertIn(option, output)

    def test_dispatch_receipt_binds_valid(self):
        code, output = self.call(*_dispatch_receipt_args())
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_dispatch_receipt_wrong_message_is_invalid(self):
        args = [a for a in _dispatch_receipt_args()]
        # Sustituye el message-file por otro archivo (digest distinto).
        args[-1] = str(FIXTURES / "task-card-valid.json")
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("message_digest", output)

    def test_dispatch_receipt_missing_max_age_lists_option(self):
        args = [a for a in _dispatch_receipt_args()
                if a != "--max-preflight-age-seconds" and a != "600"]
        # '--max-preflight-age-seconds' y '600' son adyacentes; el filtro los
        # elimina ambos. Verifica ausencia antes de llamar.
        self.assertNotIn("--max-preflight-age-seconds", args)
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("--max-preflight-age-seconds", output)

    def test_dispatch_receipt_bad_max_age_is_invalid(self):
        args = _dispatch_receipt_args()
        args[args.index("600")] = "not-a-number"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("--max-preflight-age-seconds debe ser un número", output)

    def test_dispatch_receipt_auto_amplified_policy_is_invalid(self):
        # Repro (A): la política externa (CLI) es 600; un recibo que reclama 3600
        # y dispatched 19:00 se rechaza por igualdad de política.
        receipt = json.loads((FIXTURES / "dispatch-receipt-ok.json").read_text("utf-8"))
        receipt["dispatched_at"] = "2026-08-11T19:00:00Z"
        receipt["max_preflight_age_seconds"] = 3600
        tmp = FIXTURES / "dispatch-receipt-autoamplified.json"
        tmp.write_text(json.dumps(receipt), encoding="utf-8")
        try:
            args = _dispatch_receipt_args()
            args[1] = str(tmp)
            code, output = self.call(*args)
        finally:
            tmp.unlink()
        self.assertEqual(code, 1)
        self.assertIn("política esperada", output)


class CliInapplicableBindingOptionsTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_task_card_rejects_preflight_result_option(self):
        # Repro (B): --preflight-result no puede ignorarse para task-card.
        code, output = self.call(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)

    def test_task_card_rejects_max_age_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--max-preflight-age-seconds", "600",
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)

    def test_preflight_result_rejects_preflight_result_option(self):
        # Repro (B): --preflight-result al propio preflight-result no se ignora.
        code, output = self.call(
            "validate", str(FIXTURES / "preflight-result-ok.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode", "--expected-command", "idle",
            "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a preflight-result", output)

    def test_preflight_result_rejects_max_age_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "preflight-result-ok.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode", "--expected-command", "idle",
            "--max-preflight-age-seconds", "600",
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a preflight-result", output)

    def test_audit_result_rejects_preflight_result_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a audit-result", output)

    def test_adapter_capabilities_rejects_max_age_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--max-preflight-age-seconds", "600",
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)


class CliBoundedMessageReadTests(unittest.TestCase):
    def test_oversized_message_file_rejected_via_stat_fast_path(self):
        # lstat pre-check: st_size > limit se rechaza antes de abrir (fail-closed).
        # La barrera real sigue siendo la lectura acotada; stat es sólo fast-path.
        import stat as _stat
        fake_stat = SimpleNamespace(
            st_mode=_stat.S_IFREG, st_size=_MESSAGE_MAX_BYTES + 1,
            st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1,
        )
        output = io.StringIO()
        with patch("os.lstat", return_value=fake_stat), \
                redirect_stdout(output):
            code = main(_dispatch_receipt_args())
        self.assertEqual(code, 1)
        self.assertIn("excede el límite", output.getvalue())

    def test_read_growing_after_stat_is_rejected(self):
        # TOCTOU: lstat miente (10 bytes), pero read devuelve limit+1 -> rechazo
        # por la barrera de lectura acotada, no por stat.
        import stat as _stat
        from epistates.__main__ import _safe_read_regular_file
        path = FIXTURES / "dispatch-message.txt"
        big = b"x" * (_MESSAGE_MAX_BYTES + 1)
        small = SimpleNamespace(
            st_mode=_stat.S_IFREG, st_size=10,
            st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1,
        )
        with patch("os.lstat", return_value=small), \
                patch("os.open", return_value=42), \
                patch("os.fstat", return_value=small), \
                patch("os.read", return_value=big), \
                patch("os.close"):
            with self.assertRaises(Exception) as exc:
                _safe_read_regular_file(path, _MESSAGE_MAX_BYTES)
        self.assertIn("excede el límite", str(exc.exception))

    def test_bounded_read_accepts_within_limit(self):
        from epistates.__main__ import _safe_read_message_file
        path = FIXTURES / "dispatch-message.txt"
        raw = _safe_read_message_file(path, _MESSAGE_MAX_BYTES)
        self.assertEqual(raw.decode("utf-8"), path.read_text(encoding="utf-8"))


def _human_notice_args():
    return [
        "validate", str(FIXTURES / "human-notice-ok.json"),
        "--task-card", str(FIXTURES / "task-card-valid.json"),
        "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
        "--dispatch-receipt", str(FIXTURES / "dispatch-receipt-ok.json"),
        "--run-id", "run-001", "--attempt-id", "attempt-001",
        "--expected-session-name", "epistates-opencode",
        "--max-dispatch-age-seconds", "3600",
    ]


def _review_evidence_args():
    return [
        "validate", str(FIXTURES / "review-evidence-ok.json"),
        "--task-card", str(FIXTURES / "task-card-valid.json"),
        "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
        "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
        "--dispatch-receipt", str(FIXTURES / "dispatch-receipt-ok.json"),
        "--human-notice", str(FIXTURES / "human-notice-ok.json"),
        "--run-id", "run-001", "--attempt-id", "attempt-001",
        "--expected-session-name", "epistates-opencode",
        "--expected-command", "idle",
        "--max-preflight-age-seconds", "600",
        "--max-dispatch-age-seconds", "3600",
        "--max-notice-age-seconds", "3600",
        "--message-file", str(FIXTURES / "dispatch-message.txt"),
    ]


class CliHumanNoticeTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_human_notice_requires_full_binding(self):
        code, output = self.call("validate", str(FIXTURES / "human-notice-ok.json"))
        self.assertEqual(code, 1)
        self.assertIn("human-notice requiere", output)
        for option in ("--dispatch-receipt", "--max-dispatch-age-seconds",
                       "--task-card", "--expected-session-name"):
            self.assertIn(option, output)

    def test_human_notice_binds_valid(self):
        code, output = self.call(*_human_notice_args())
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_human_notice_wrong_session_is_invalid(self):
        args = _human_notice_args()
        args[args.index("epistates-opencode")] = "wrong-session"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("session_name", output)

    def test_human_notice_bad_max_dispatch_age_is_invalid(self):
        args = _human_notice_args()
        args[args.index("3600")] = "not-a-number"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("--max-dispatch-age-seconds debe ser un número", output)

    def test_human_notice_auto_amplified_policy_is_invalid(self):
        notice = json.loads((FIXTURES / "human-notice-ok.json").read_text("utf-8"))
        notice["notified_at"] = "2026-08-11T20:00:00Z"
        notice["max_dispatch_age_seconds"] = 7200
        tmp = FIXTURES / "human-notice-autoamplified.json"
        tmp.write_text(json.dumps(notice), encoding="utf-8")
        try:
            args = _human_notice_args()
            args[1] = str(tmp)
            code, output = self.call(*args)
        finally:
            tmp.unlink()
        self.assertEqual(code, 1)
        self.assertIn("política esperada", output)


class CliReviewEvidenceTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_review_evidence_requires_full_binding(self):
        code, output = self.call("validate", str(FIXTURES / "review-evidence-ok.json"))
        self.assertEqual(code, 1)
        self.assertIn("review-evidence requiere", output)
        for option in ("--human-notice", "--dispatch-receipt",
                       "--max-notice-age-seconds", "--message-file"):
            self.assertIn(option, output)

    def test_review_evidence_binds_valid(self):
        code, output = self.call(*_review_evidence_args())
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_review_evidence_wrong_message_is_invalid(self):
        args = _review_evidence_args()
        args[-1] = str(FIXTURES / "task-card-valid.json")
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("message_digest", output)

    def test_review_evidence_auto_amplified_notice_policy_is_invalid(self):
        evidence = json.loads((FIXTURES / "review-evidence-ok.json").read_text("utf-8"))
        evidence["max_notice_age_seconds"] = 7200
        tmp = FIXTURES / "review-evidence-autoamplified.json"
        tmp.write_text(json.dumps(evidence), encoding="utf-8")
        try:
            args = _review_evidence_args()
            args[1] = str(tmp)
            code, output = self.call(*args)
        finally:
            tmp.unlink()
        self.assertEqual(code, 1)
        self.assertIn("política esperada", output)


class CliNewSchemaInapplicableOptionsTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_task_card_rejects_dispatch_receipt_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--dispatch-receipt", str(FIXTURES / "dispatch-receipt-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)

    def test_task_card_rejects_human_notice_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--human-notice", str(FIXTURES / "human-notice-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)

    def test_human_notice_rejects_preflight_result_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "human-notice-ok.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--dispatch-receipt", str(FIXTURES / "dispatch-receipt-ok.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode",
            "--max-dispatch-age-seconds", "3600",
            "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a human-notice", output)

    def test_human_notice_rejects_message_file_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "human-notice-ok.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--dispatch-receipt", str(FIXTURES / "dispatch-receipt-ok.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode",
            "--max-dispatch-age-seconds", "3600",
            "--message-file", str(FIXTURES / "dispatch-message.txt"),
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a human-notice", output)

    def test_dispatch_receipt_rejects_human_notice_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "dispatch-receipt-ok.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode",
            "--expected-command", "idle",
            "--max-preflight-age-seconds", "600",
            "--message-file", str(FIXTURES / "dispatch-message.txt"),
            "--human-notice", str(FIXTURES / "human-notice-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a dispatch-receipt", output)

    def test_review_evidence_rejects_nothing_when_complete(self):
        # review-evidence admite todas las opciones de la cadena de revisión; no
        # debe rechazar ninguna. Las opciones de decisión de auditoría sí se
        # rechazan (no aplican a review-evidence).
        code, output = self.call(*_review_evidence_args())
        self.assertEqual(code, 0)


def _audit_review_args():
    """Argumentos CLI completos para validar audit-result en modo puente."""
    return [
        "validate", str(FIXTURES / "audit-result-review-bound.json"),
        "--task-card", str(FIXTURES / "task-card-valid.json"),
        "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
        "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
        "--dispatch-receipt", str(FIXTURES / "dispatch-receipt-ok.json"),
        "--human-notice", str(FIXTURES / "human-notice-ok.json"),
        "--review-evidence", str(FIXTURES / "review-evidence-ok.json"),
        "--run-id", "run-001", "--attempt-id", "attempt-001",
        "--expected-session-name", "epistates-opencode",
        "--expected-command", "idle",
        "--max-preflight-age-seconds", "600",
        "--max-dispatch-age-seconds", "3600",
        "--max-notice-age-seconds", "3600",
        "--message-file", str(FIXTURES / "dispatch-message.txt"),
        "--expected-classification", "OK",
        "--expected-decision", "proceed",
        "--expected-decision-reference", "conversation-2026-08-11",
        "--expected-observed-at", "2026-08-11T19:00:00Z",
        "--max-audit-age-seconds", "3600",
        "--expected-grant-id", "maintainer-e1-contracts",
        "--expected-grant-digest", "sha256:24a39dff4b7a38f45959b89850debed2bb584fb4c887278748064ed6f1eda2cd",
    ]


class CliAuditReviewBridgeTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_audit_review_requires_full_binding(self):
        code, output = self.call("validate", str(FIXTURES / "audit-result-review-bound.json"))
        self.assertEqual(code, 1)
        self.assertIn("audit-result requiere", output)
        for option in ("--review-evidence", "--expected-classification",
                       "--expected-decision", "--expected-decision-reference",
                       "--expected-observed-at", "--max-audit-age-seconds",
                       "--expected-grant-id", "--expected-grant-digest",
                       "--human-notice", "--message-file"):
            self.assertIn(option, output)

    def test_audit_review_binds_valid(self):
        code, output = self.call(*_audit_review_args())
        self.assertEqual(code, 0)
        self.assertIn("VALID", output)

    def test_audit_review_wrong_expected_decision_is_invalid(self):
        args = _audit_review_args()
        args[args.index("proceed")] = "escalate"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("decision", output)

    def test_audit_review_wrong_expected_classification_is_invalid(self):
        args = _audit_review_args()
        args[args.index("OK")] = "BLOQ"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("classification", output)

    def test_audit_review_wrong_decision_reference_is_invalid(self):
        args = _audit_review_args()
        args[args.index("conversation-2026-08-11")] = "other-reference"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("decision_reference", output)

    def test_audit_review_wrong_expected_observed_at_is_invalid(self):
        args = _audit_review_args()
        args[args.index("2026-08-11T19:00:00Z")] = "2026-08-11T19:01:00Z"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("observed_at", output)

    def test_audit_review_future_observed_at_is_invalid(self):
        args = _audit_review_args()
        args[args.index("2026-08-11T19:00:00Z")] = "2099-01-01T00:00:00Z"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("observed_at", output)

    def test_audit_review_bad_max_audit_age_is_invalid(self):
        args = _audit_review_args()
        idx = args.index("--max-audit-age-seconds")
        args[idx + 1] = "not-a-number"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("--max-audit-age-seconds debe ser un número", output)

    def test_audit_review_wrong_expected_grant_id_is_invalid(self):
        args = _audit_review_args()
        args[args.index("maintainer-e1-contracts")] = "other-grant"
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("grant_id", output)

    def test_audit_review_wrong_expected_grant_digest_is_invalid(self):
        args = _audit_review_args()
        args[args.index("sha256:24a39dff4b7a38f45959b89850debed2bb584fb4c887278748064ed6f1eda2cd")] = "sha256:" + "0" * 64
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("grant_digest", output)

    def test_audit_review_misbound_review_evidence_is_invalid(self):
        # review-evidence con digest alterado no liga con el audit-result.
        ev = json.loads((FIXTURES / "review-evidence-ok.json").read_text("utf-8"))
        ev["capture_digest"] = "sha256:" + "9" * 64
        tmp = FIXTURES / "review-evidence-altered.json"
        tmp.write_text(json.dumps(ev), encoding="utf-8")
        try:
            args = _audit_review_args()
            args[args.index(str(FIXTURES / "review-evidence-ok.json"))] = str(tmp)
            code, output = self.call(*args)
        finally:
            tmp.unlink()
        self.assertEqual(code, 1)


class CliAuditDecisionOptionsInapplicableTests(unittest.TestCase):
    """Las opciones de decisión de auditoría sólo aplican al audit-result puente."""

    def call(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue()

    def test_h2_audit_result_rejects_review_evidence_option(self):
        # audit-result H2 (sin review_evidence_digest) no acepta --review-evidence.
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--review-evidence", str(FIXTURES / "review-evidence-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a audit-result", output)

    def test_h2_audit_result_rejects_expected_classification_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-classification", "OK",
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a audit-result", output)

    def test_h2_audit_result_rejects_expected_observed_at_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-observed-at", "2026-08-11T19:00:00Z",
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a audit-result", output)

    def test_h2_audit_result_rejects_max_audit_age_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--max-audit-age-seconds", "3600",
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a audit-result", output)

    def test_h2_audit_result_rejects_expected_grant_id_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-grant-id", "maintainer-e1-contracts",
        )
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a audit-result", output)

    def test_task_card_rejects_review_evidence_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--review-evidence", str(FIXTURES / "review-evidence-ok.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)

    def test_task_card_rejects_max_audit_age_option(self):
        code, output = self.call(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--max-audit-age-seconds", "3600",
        )
        self.assertEqual(code, 1)
        self.assertIn("sólo aplican", output)

    def test_review_evidence_rejects_expected_decision_option(self):
        # --expected-decision no aplica a review-evidence (sólo al audit-result).
        args = _review_evidence_args()
        args += ["--expected-decision", "proceed"]
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a review-evidence", output)

    def test_review_evidence_rejects_review_evidence_option(self):
        args = _review_evidence_args()
        args += ["--review-evidence", str(FIXTURES / "review-evidence-ok.json")]
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a review-evidence", output)

    def test_review_evidence_rejects_expected_grant_digest_option(self):
        args = _review_evidence_args()
        args += ["--expected-grant-digest", "sha256:" + "0" * 64]
        code, output = self.call(*args)
        self.assertEqual(code, 1)
        self.assertIn("inaplicables a review-evidence", output)
