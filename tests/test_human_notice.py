import inspect
import json
import unittest
from pathlib import Path

from epistates.contracts import ValidationError
from epistates.human_notice import (
    HumanNoticeError,
    _EVENT_CATALOG,
    _MAX_DISPATCH_AGE_CEILING,
    validate_human_notice,
    validate_human_notice_binding,
)


FIXTURES = Path(__file__).parent.parent / "fixtures"
NOTICE_SRC = Path(inspect.getsourcefile(validate_human_notice_binding)).read_text(encoding="utf-8")

TASK_ID = "e1-contracts"
RUN_ID = "run-001"
ATTEMPT_ID = "attempt-001"
SESSION = "epistates-opencode"
MAX_DISPATCH_AGE = 3600


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _task():
    return load("task-card-valid.json")


def _adapter():
    return load("adapter-capabilities-opencode-tmux.json")


def _receipt():
    return load("dispatch-receipt-ok.json")


def _notice():
    return load("human-notice-ok.json")


def _bind(
    notice=None, task=None, adapter=None, receipt=None,
    run_id=RUN_ID, attempt_id=ATTEMPT_ID, session=SESSION,
    expected_max=MAX_DISPATCH_AGE,
):
    if notice is None:
        notice = _notice()
    if task is None:
        task = _task()
    if adapter is None:
        adapter = _adapter()
    if receipt is None:
        receipt = _receipt()
    validate_human_notice_binding(
        notice, task, adapter, receipt,
        run_id, attempt_id, session, expected_max,
    )


# ---------------------------------------------------------------------------
# Estructura: catálogo, campos cerrados, sin texto libre.
# ---------------------------------------------------------------------------


class StructureTests(unittest.TestCase):
    def test_fixture_notice_is_valid(self):
        validate_human_notice(_notice())

    def test_fixture_notice_binds(self):
        _bind()

    def test_event_catalog_is_closed(self):
        self.assertEqual(_EVENT_CATALOG, frozenset({"external_completion"}))

    def test_unknown_event_fails(self):
        notice = _notice()
        notice["event_id"] = "agent_says_done"
        with self.assertRaises(ValidationError):
            validate_human_notice(notice)

    def test_extra_field_fails(self):
        notice = _notice()
        notice["free_text"] = "the agent finished"
        with self.assertRaises(ValidationError):
            validate_human_notice(notice)

    def test_missing_field_fails(self):
        notice = _notice()
        del notice["event_id"]
        with self.assertRaises(ValidationError):
            validate_human_notice(notice)

    def test_no_command_or_prompt_field_exists(self):
        # El aviso nunca transporta comando, prompt ni autoridad.
        for forbidden in ("command", "prompt", "message", "authority", "instructions"):
            self.assertNotIn(forbidden, _notice())

    def test_bad_schema_fails(self):
        notice = _notice()
        notice["schema"] = "epistates/other/v1"
        with self.assertRaises(ValidationError):
            validate_human_notice(notice)


# ---------------------------------------------------------------------------
# Binding: cero llamadas implícitas; fallos cerrados.
# ---------------------------------------------------------------------------


class BindingFailClosedTests(unittest.TestCase):
    def test_wrong_task_id_fails(self):
        task = _task()
        task = dict(task, task_id="other-task-id")
        with self.assertRaises(ValidationError):
            _bind(task=task)

    def test_wrong_run_id_fails(self):
        with self.assertRaises(ValidationError):
            _bind(run_id="run-999")

    def test_wrong_attempt_id_fails(self):
        with self.assertRaises(ValidationError):
            _bind(attempt_id="attempt-999")

    def test_wrong_session_fails(self):
        with self.assertRaises(ValidationError):
            _bind(session="other-session")

    def test_wrong_task_card_digest_fails(self):
        notice = _notice()
        notice["task_card_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(notice=notice)

    def test_wrong_adapter_digest_fails(self):
        notice = _notice()
        notice["adapter_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(notice=notice)

    def test_wrong_dispatch_receipt_digest_fails(self):
        notice = _notice()
        notice["dispatch_receipt_digest"] = "sha256:" + "f" * 64
        with self.assertRaises(ValidationError):
            _bind(notice=notice)

    def test_misbound_receipt_session_fails(self):
        receipt = _receipt()
        receipt = dict(receipt, session_name="otra")
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt)


# ---------------------------------------------------------------------------
# Política de frescura inyectada y anti-auto-amplificación.
# ---------------------------------------------------------------------------


class FreshnessPolicyTests(unittest.TestCase):
    def test_notified_preceding_dispatched_fails(self):
        notice = _notice()
        notice["notified_at"] = "2026-08-11T17:00:00Z"  # dispatched es 18:00
        with self.assertRaises(ValidationError):
            _bind(notice=notice)

    def test_stale_noticed_fails(self):
        # dispatched 18:00, notified 20:00 (7200s); max 3600s -> stale.
        notice = _notice()
        notice["notified_at"] = "2026-08-11T20:00:00Z"
        with self.assertRaises(ValidationError):
            _bind(notice=notice)

    def test_auto_amplified_policy_fails(self):
        # El aviso reclama 7200 y notified 20:00; la política externa es 3600.
        notice = _notice()
        notice["notified_at"] = "2026-08-11T20:00:00Z"
        notice["max_dispatch_age_seconds"] = 7200
        with self.assertRaises(ValidationError):
            _bind(notice=notice, expected_max=MAX_DISPATCH_AGE)

    def test_expected_policy_distinct_fails(self):
        with self.assertRaises(ValidationError):
            _bind(expected_max=1800)

    def test_negative_policy_fails(self):
        with self.assertRaises(ValidationError):
            _bind(expected_max=-5)

    def test_zero_policy_fails(self):
        with self.assertRaises(ValidationError):
            _bind(expected_max=0)

    def test_over_ceiling_policy_fails(self):
        with self.assertRaises(ValidationError):
            _bind(expected_max=_MAX_DISPATCH_AGE_CEILING + 1)

    def test_non_finite_policy_fails(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                _bind(expected_max=bad)

    def test_exact_boundary_age_is_accepted(self):
        # dispatched 18:00, notified 19:00 (3600s) == max 3600: OK (<=).
        notice = _notice()
        notice["notified_at"] = "2026-08-11T19:00:00Z"
        _bind(notice=notice, expected_max=3600)

    def test_external_policy_rederives_freshness(self):
        # Igualdad a 7200 y notified 1h después de dispatched (3600s): OK.
        notice = _notice()
        notice["notified_at"] = "2026-08-11T19:00:00Z"
        notice["max_dispatch_age_seconds"] = 7200
        _bind(notice=notice, expected_max=7200)


# ---------------------------------------------------------------------------
# Determinismo y ausencia de reloj/polling.
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_same_binding(self):
        # El binding es determinista: no consulta reloj.
        _bind()
        _bind()

    def test_source_reads_no_clock(self):
        self.assertNotIn("datetime.now", NOTICE_SRC)
        self.assertNotIn("datetime.utcnow", NOTICE_SRC)
        self.assertNotIn("time.time", NOTICE_SRC)
        self.assertNotIn("time.sleep", NOTICE_SRC)

    def test_source_has_no_subprocess(self):
        self.assertNotIn("subprocess", NOTICE_SRC)
        self.assertNotIn("os.system", NOTICE_SRC)


if __name__ == "__main__":
    unittest.main()
