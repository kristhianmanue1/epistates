import json
import unittest
from pathlib import Path

from epistates.audit import canonical_digest, validate_audit_binding, validate_audit_result
from epistates.contracts import ValidationError


FIXTURES = Path(__file__).parent.parent / "fixtures"


class AuditResultTests(unittest.TestCase):
    def load_fixture(self, name="audit-result-valid.json"):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def load_task(self):
        return json.loads((FIXTURES / "task-card-valid.json").read_text(encoding="utf-8"))

    def test_valid_ok_result_has_valid_binding(self):
        result = self.load_fixture()
        validate_audit_result(result)
        task = self.load_task()
        validate_audit_binding(result, task, "run-001", "attempt-001")

    def test_ok_rejects_missing_evidence(self):
        with self.assertRaisesRegex(ValidationError, "OK exige"):
            validate_audit_result(self.load_fixture("audit-result-invalid-ok-missing.json"))

    def test_missing_requires_null_digest(self):
        result = self.load_fixture()
        result["classification"] = "PARCIAL"
        result["decision"] = "escalate"
        result["evidence"][0] = {"evidence_id": "git_status", "status": "missing", "digest": "sha256:" + "1" * 64}
        with self.assertRaisesRegex(ValidationError, "digest null"):
            validate_audit_result(result)

    def test_rejects_duplicate_evidence(self):
        result = self.load_fixture()
        result["evidence"].append(dict(result["evidence"][0]))
        with self.assertRaisesRegex(ValidationError, "duplicado"):
            validate_audit_result(result)

    def test_rejects_unknown_outcome_pair(self):
        result = self.load_fixture()
        result["classification"] = "BLOQ"
        result["decision"] = "proceed"
        with self.assertRaisesRegex(ValidationError, "no permitida"):
            validate_audit_result(result)

    def test_rejects_noncanonical_timestamp(self):
        result = self.load_fixture()
        result["observed_at"] = "2026-08-11 18:00:00Z"
        with self.assertRaisesRegex(ValidationError, "RFC3339"):
            validate_audit_result(result)

    def test_rejects_bad_types_without_traceback(self):
        result = self.load_fixture()
        result["evidence"][0]["status"] = []
        with self.assertRaises(ValidationError):
            validate_audit_result(result)
        result = self.load_fixture()
        result["classification"] = []
        with self.assertRaises(ValidationError):
            validate_audit_result(result)

    def test_binding_rejects_wrong_card_or_grant_digest(self):
        result = self.load_fixture()
        task = self.load_task()
        result["task_card_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValidationError, "task_card_digest"):
            validate_audit_binding(result, task, "run-001", "attempt-001")
        result = self.load_fixture()
        result["authority_binding"]["grant_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValidationError, "grant_digest"):
            validate_audit_binding(result, task, "run-001", "attempt-001")

    def test_binding_requires_every_card_evidence_id(self):
        result = self.load_fixture()
        task = self.load_task()
        result["classification"] = "PARCIAL"
        result["decision"] = "escalate"
        result["evidence"] = [result["evidence"][0]]
        with self.assertRaisesRegex(ValidationError, "evidencia requerida ausente"):
            validate_audit_binding(result, task, "run-001", "attempt-001")

    def test_binding_requires_expected_run_and_attempt(self):
        result = self.load_fixture()
        task = self.load_task()
        with self.assertRaisesRegex(ValidationError, "run_id no coincide"):
            validate_audit_binding(result, task, "run-999", "attempt-001")
        with self.assertRaisesRegex(ValidationError, "attempt_id no coincide"):
            validate_audit_binding(result, task, "run-001", "attempt-999")

    def test_all_card_checks_are_always_required(self):
        result = self.load_fixture()
        task = self.load_task()
        task["evidence"]["required"] = ["worktree_status"]
        result["task_card_digest"] = canonical_digest(task)
        result["evidence"] = [result["evidence"][0]]
        with self.assertRaisesRegex(ValidationError, "unit_tests"):
            validate_audit_binding(result, task, "run-001", "attempt-001")

    def test_fixture_digests_are_canonical(self):
        result = self.load_fixture()
        task = self.load_task()
        self.assertEqual(result["task_card_digest"], canonical_digest(task))
        self.assertEqual(result["authority_binding"]["grant_digest"], canonical_digest(task["authority"]))
