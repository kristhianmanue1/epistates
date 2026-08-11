import json
import unittest
from pathlib import Path

from epistates.state import TransitionError, apply_audit, transition


FIXTURES = Path(__file__).parent.parent / "fixtures"


class StateMachineTests(unittest.TestCase):
    def load_audit(self):
        return json.loads((FIXTURES / "audit-result-valid.json").read_text(encoding="utf-8"))

    def load_task(self):
        return json.loads((FIXTURES / "task-card-valid.json").read_text(encoding="utf-8"))

    def test_nominal_sequence_reaches_done_only_through_audit(self):
        state = "PREPARED"
        for event in ("dispatch", "wait", "notify", "review"):
            state = transition(state, event)
        self.assertEqual(state, "REVIEWING")
        self.assertEqual(
            apply_audit(state, self.load_audit(), self.load_task(), "run-001", "attempt-001"),
            "DONE",
        )

    def test_correction_returns_to_waiting(self):
        result = self.load_audit()
        result["classification"] = "PARCIAL"
        result["decision"] = "fix-and-retry"
        state = apply_audit("REVIEWING", result, self.load_task(), "run-001", "attempt-001")
        self.assertEqual(state, "CORRECTION_SENT")
        self.assertEqual(transition(state, "wait"), "WAITING_EXTERNAL")

    def test_terminal_states_reject_events(self):
        for state in ("DONE", "BLOCKED"):
            with self.assertRaisesRegex(TransitionError, "terminal"):
                transition(state, "notify")

    def test_unknown_transition_fails_closed(self):
        with self.assertRaisesRegex(TransitionError, "no permitida"):
            transition("PREPARED", "review")

    def test_reviewing_cannot_block_without_audit(self):
        with self.assertRaisesRegex(TransitionError, "no permitida"):
            transition("REVIEWING", "block")

    def test_bad_transition_types_fail_closed(self):
        with self.assertRaisesRegex(TransitionError, "desconocido"):
            transition([], "dispatch")

    def test_audit_requires_reviewing(self):
        with self.assertRaisesRegex(TransitionError, "sólo puede"):
            apply_audit("REVIEW_READY", self.load_audit(), self.load_task(), "run-001", "attempt-001")
