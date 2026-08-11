import json
import unittest
from pathlib import Path

from epistates.contracts import ValidationError, validate_task_card


FIXTURES = Path(__file__).parent.parent / "fixtures"


class TaskCardValidationTests(unittest.TestCase):
    def load_fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_accepts_complete_card(self):
        validate_task_card(self.load_fixture("task-card-valid.json"))

    def test_rejects_missing_explicit_prohibitions(self):
        with self.assertRaisesRegex(ValidationError, "campos requeridos ausentes"):
            validate_task_card(self.load_fixture("task-card-missing-prohibitions.json"))

    def test_rejects_implicit_protected_operation(self):
        card = self.load_fixture("task-card-valid.json")
        card["forbidden_operations"].remove("push")
        with self.assertRaisesRegex(ValidationError, "sin prohibición explícita: push"):
            validate_task_card(card)

    def test_rejects_path_outside_worktree(self):
        card = self.load_fixture("task-card-valid.json")
        card["allowed_paths"] = ["../outside/"]
        with self.assertRaisesRegex(ValidationError, "dentro del worktree"):
            validate_task_card(card)

    def test_rejects_unknown_or_arbitrary_check(self):
        card = self.load_fixture("task-card-valid.json")
        card["checks"][0]["check_id"] = "git commit -m unsafe"
        with self.assertRaisesRegex(ValidationError, "catálogo confiable"):
            validate_task_card(card)

    def test_rejects_missing_authority_or_evidence(self):
        card = self.load_fixture("task-card-valid.json")
        del card["authority"]
        with self.assertRaisesRegex(ValidationError, "campos requeridos ausentes: authority"):
            validate_task_card(card)
        card = self.load_fixture("task-card-valid.json")
        del card["evidence"]
        with self.assertRaisesRegex(ValidationError, "campos requeridos ausentes: evidence"):
            validate_task_card(card)

    def test_rejects_whitespace_only_text(self):
        card = self.load_fixture("task-card-valid.json")
        card["objective"] = "   "
        with self.assertRaisesRegex(ValidationError, "objective debe ser texto"):
            validate_task_card(card)

    def test_rejects_input_outside_worktree(self):
        card = self.load_fixture("task-card-valid.json")
        card["inputs"] = ["../../secret"]
        with self.assertRaisesRegex(ValidationError, "inputs debe permanecer"):
            validate_task_card(card)

    def test_rejects_relative_worktree(self):
        card = self.load_fixture("task-card-valid.json")
        card["target"]["worktree"] = "workspace/epistates"
        with self.assertRaisesRegex(ValidationError, "ruta absoluta"):
            validate_task_card(card)

    def test_rejects_root_or_non_normalized_worktree(self):
        card = self.load_fixture("task-card-valid.json")
        card["target"]["worktree"] = "/"
        with self.assertRaisesRegex(ValidationError, "normalizada"):
            validate_task_card(card)
        card["target"]["worktree"] = "/safe/../outside"
        with self.assertRaisesRegex(ValidationError, "normalizada"):
            validate_task_card(card)
        card["target"]["worktree"] = "//tmp"
        with self.assertRaisesRegex(ValidationError, "normalizada"):
            validate_task_card(card)

    def test_rejects_bad_json_types_without_traceback(self):
        card = self.load_fixture("task-card-valid.json")
        card["role"] = []
        with self.assertRaises(ValidationError):
            validate_task_card(card)
        card = self.load_fixture("task-card-valid.json")
        card["checks"][0]["check_id"] = []
        with self.assertRaises(ValidationError):
            validate_task_card(card)

    def test_rejects_noncanonical_grant_id(self):
        card = self.load_fixture("task-card-valid.json")
        card["authority"]["grant_id"] = "Grant reference / 2026"
        with self.assertRaisesRegex(ValidationError, "grant_id"):
            validate_task_card(card)

    def test_rejects_lone_unicode_surrogate(self):
        card = self.load_fixture("task-card-valid.json")
        card["objective"] = "\ud800"
        with self.assertRaises(ValidationError):
            validate_task_card(card)
