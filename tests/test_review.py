import inspect
import json
import unittest
from pathlib import Path

from epistates.contracts import ValidationError
from epistates.review import (
    IndeterminateReviewError,
    ReviewError,
    _MAX_NOTICE_AGE_CEILING,
    _PHASES,
    _required_checks,
    review_opencode_tmux,
    validate_review_evidence,
    validate_review_evidence_binding,
)
from epistates.review_runner import CaptureOutcome, CheckOutcome


REVIEW_SRC = Path(inspect.getsourcefile(review_opencode_tmux)).read_text(encoding="utf-8")
FIXTURES = Path(__file__).parent.parent / "fixtures"

TASK_ID = "e1-contracts"
RUN_ID = "run-001"
ATTEMPT_ID = "attempt-001"
SESSION = "epistates-opencode"
COMMAND = "idle"
MESSAGE = "Ejecuta el corte H3-Slice3: entrega literal opencode-tmux y detente."
MAX_PREFLIGHT_AGE = 600
MAX_DISPATCH_AGE = 3600
MAX_NOTICE_AGE = 3600
REVIEWED_AT = "2026-08-11T18:45:00Z"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _task():
    return load("task-card-valid.json")


def _adapter():
    return load("adapter-capabilities-opencode-tmux.json")


def _preflight():
    return load("preflight-result-ok.json")


def _receipt():
    return load("dispatch-receipt-ok.json")


def _notice():
    return load("human-notice-ok.json")


class FakeRunner:
    """Runner inyectable determinista que registra cada llamada cerrada."""

    def __init__(self, *, capture_error=None, check_errors=None,
                 capture_outcome=None, check_outcomes=None):
        self.capture_calls = []
        self.check_calls = []
        self._capture_error = capture_error
        self._check_errors = check_errors or {}
        self._capture_outcome = capture_outcome or CaptureOutcome(
            digest="sha256:" + "a" * 64, length_utf8=42, capture_lines=50,
        )
        self._check_outcomes = check_outcomes or {}

    def capture_once(self, session_name):
        self.capture_calls.append(session_name)
        if self._capture_error is not None:
            raise self._capture_error
        return self._capture_outcome

    def run_check(self, check_id):
        self.check_calls.append(check_id)
        if check_id in self._check_errors:
            raise self._check_errors[check_id]
        return self._check_outcomes.get(
            check_id,
            CheckOutcome(check_id, "pass", "sha256:" + "b" * 64, 0),
        )


def _default_kwargs(**overrides):
    kwargs = dict(
        expected_run_id=RUN_ID,
        expected_attempt_id=ATTEMPT_ID,
        expected_session_name=SESSION,
        expected_command=COMMAND,
        message=MESSAGE,
        expected_max_preflight_age_seconds=MAX_PREFLIGHT_AGE,
        expected_max_dispatch_age_seconds=MAX_DISPATCH_AGE,
        expected_max_notice_age_seconds=MAX_NOTICE_AGE,
        reviewed_at=REVIEWED_AT,
        current_state="WAITING_EXTERNAL",
        runner=FakeRunner(),
    )
    kwargs.update(overrides)
    return kwargs


_SENTINEL = object()


def _review(runner=_SENTINEL, **overrides):
    task = overrides.pop("task", None) or _task()
    adapter = overrides.pop("adapter", None) or _adapter()
    preflight = overrides.pop("preflight", None) or _preflight()
    receipt = overrides.pop("receipt", None) or _receipt()
    notice = overrides.pop("notice", None) or _notice()
    kwargs = _default_kwargs()
    kwargs.update(overrides)
    if runner is not _SENTINEL:
        kwargs["runner"] = runner
    return review_opencode_tmux(
        task, adapter, preflight, receipt, notice, **kwargs,
    )


def _bind(
    evidence=None, preflight=None, receipt=None, notice=None, message=None,
    run_id=RUN_ID, attempt_id=ATTEMPT_ID, session=SESSION, command=COMMAND,
    expected_preflight_age=MAX_PREFLIGHT_AGE, expected_dispatch_age=MAX_DISPATCH_AGE,
    expected_notice_age=MAX_NOTICE_AGE,
):
    if evidence is None:
        evidence = load("review-evidence-ok.json")
    if preflight is None:
        preflight = _preflight()
    if receipt is None:
        receipt = _receipt()
    if notice is None:
        notice = _notice()
    if message is None:
        message = MESSAGE
    validate_review_evidence_binding(
        evidence, _task(), _adapter(), preflight, receipt, notice,
        run_id, attempt_id, session, command,
        expected_preflight_age, message,
        expected_dispatch_age, expected_notice_age,
    )


# ---------------------------------------------------------------------------
# Resolución de checks desde la tarjeta (catálogo, orden determinista).
# ---------------------------------------------------------------------------


class RequiredChecksTests(unittest.TestCase):
    def test_required_checks_sorted_from_card(self):
        self.assertEqual(_required_checks(_task()), ["diff_check", "git_status", "unit_tests"])


# ---------------------------------------------------------------------------
# Éxito: exactamente una captura y cada check una vez, en orden.
# ---------------------------------------------------------------------------


class SingleCaptureAndChecksTests(unittest.TestCase):
    def test_success_makes_one_capture_and_each_check_once(self):
        runner = FakeRunner()
        evidence, state = _review(runner=runner)
        self.assertEqual(runner.capture_calls, [SESSION])
        self.assertEqual(len(runner.capture_calls), 1)
        self.assertEqual(runner.check_calls, ["diff_check", "git_status", "unit_tests"])
        self.assertEqual(state, "REVIEWING")

    def test_no_polling_no_extra_capture(self):
        runner = FakeRunner()
        _review(runner=runner)
        self.assertEqual(len(runner.capture_calls), 1)
        self.assertEqual(len(runner.check_calls), 3)

    def test_checks_run_in_deterministic_sorted_order(self):
        runner = FakeRunner()
        _review(runner=runner)
        self.assertEqual(runner.check_calls, sorted(runner.check_calls))

    def test_evidence_final_state_and_phases(self):
        evidence, _ = _review()
        self.assertEqual(evidence["final_state"], "REVIEWING")
        self.assertEqual(evidence["phases_confirmed"], list(_PHASES))
        self.assertEqual(evidence["confirms"], "inspection_only")

    def test_evidence_carries_binding_digests(self):
        from epistates.audit import canonical_digest
        evidence, _ = _review()
        self.assertEqual(evidence["task_card_digest"], canonical_digest(_task()))
        self.assertEqual(evidence["adapter_digest"], canonical_digest(_adapter()))
        self.assertEqual(evidence["preflight_result_digest"], canonical_digest(_preflight()))
        self.assertEqual(evidence["dispatch_receipt_digest"], canonical_digest(_receipt()))
        self.assertEqual(evidence["human_notice_digest"], canonical_digest(_notice()))

    def test_evidence_does_not_persist_capture_content(self):
        runner = FakeRunner()
        evidence, _ = _review(runner=runner)
        rendered = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("capture_text", evidence)
        self.assertNotIn("stdout", evidence)
        self.assertNotIn("stderr", evidence)
        self.assertIn("capture_digest", evidence)
        self.assertIn("capture_length_utf8", evidence)


# ---------------------------------------------------------------------------
# Cero llamadas cuando la cadena falla antes del efecto.
# ---------------------------------------------------------------------------


class ZeroCallsBeforeChainValidTests(unittest.TestCase):
    def _assert_zero(self, **overrides):
        runner = overrides.pop("runner", _SENTINEL)
        if runner is _SENTINEL:
            runner = FakeRunner()
        with self.assertRaises(ReviewError):
            _review(runner=runner, **overrides)
        if hasattr(runner, "capture_calls"):
            self.assertEqual(runner.capture_calls, [])
            self.assertEqual(runner.check_calls, [])

    def test_wrong_state_makes_zero_calls(self):
        for bad in ("PREPARED", "DISPATCHED", "REVIEW_READY", "REVIEWING", "DONE", "BLOCKED"):
            self._assert_zero(current_state=bad)

    def test_none_runner_makes_zero_calls(self):
        self._assert_zero(runner=None)

    def test_misbound_run_id_makes_zero_calls(self):
        self._assert_zero(expected_run_id="run-999")

    def test_misbound_command_makes_zero_calls(self):
        self._assert_zero(expected_command="wrong")

    def test_wrong_session_makes_zero_calls(self):
        self._assert_zero(expected_session_name="other")

    def test_bad_reviewed_timestamp_makes_zero_calls(self):
        self._assert_zero(reviewed_at="2026-08-11 18:45:00Z")

    def test_notice_binding_failure_makes_zero_calls(self):
        # Aviso mal ligado (digest del recibo alterado): cero llamadas.
        notice = _notice()
        notice["dispatch_receipt_digest"] = "sha256:" + "0" * 64
        self._assert_zero(notice=notice)

    def test_dispatch_binding_failure_makes_zero_calls(self):
        # Recibo mal ligado al preflight: cero llamadas.
        receipt = _receipt()
        receipt["preflight_result_digest"] = "sha256:" + "0" * 64
        self._assert_zero(receipt=receipt)

    def test_stale_review_freshness_makes_zero_calls(self):
        # notified 18:30, reviewed demasiado tarde (> 3600s).
        self._assert_zero(reviewed_at="2026-08-11T20:00:00Z")

    def test_reviewed_preceding_noticed_makes_zero_calls(self):
        self._assert_zero(reviewed_at="2026-08-11T18:00:00Z")

    def test_bad_dispatch_age_policy_makes_zero_calls(self):
        self._assert_zero(expected_max_dispatch_age_seconds=-5)

    def test_bad_notice_age_policy_makes_zero_calls(self):
        self._assert_zero(expected_max_notice_age_seconds=0)

    def test_extra_notice_field_makes_zero_calls(self):
        notice = _notice()
        notice["free_text"] = "agent finished"
        self._assert_zero(notice=notice)


# ---------------------------------------------------------------------------
# Frescura: anti-auto-amplificación y rederiva con política externa.
# ---------------------------------------------------------------------------


class FreshnessPolicyTests(unittest.TestCase):
    def test_over_ceiling_notice_age_rejected_zero_calls(self):
        runner = FakeRunner()
        with self.assertRaises(ReviewError):
            _review(runner=runner, expected_max_notice_age_seconds=_MAX_NOTICE_AGE_CEILING + 1)
        self.assertEqual(runner.capture_calls, [])

    def test_non_finite_notice_age_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            runner = FakeRunner()
            with self.assertRaises(ReviewError, msg=repr(bad)):
                _review(runner=runner, expected_max_notice_age_seconds=bad)
            self.assertEqual(runner.capture_calls, [])

    def test_exact_boundary_notice_age_accepted(self):
        # notified 18:30, reviewed 19:30 (3600s) == max 3600: OK (<=).
        runner = FakeRunner()
        evidence, _ = _review(
            runner=runner,
            reviewed_at="2026-08-11T19:30:00Z",
            expected_max_notice_age_seconds=3600,
        )
        self.assertEqual(evidence["final_state"], "REVIEWING")


# ---------------------------------------------------------------------------
# Sin reintento: captura o check fallido es indeterminado.
# ---------------------------------------------------------------------------


class NoRetryIndeterminateTests(unittest.TestCase):
    def test_capture_failure_is_indeterminate_no_checks(self):
        runner = FakeRunner(capture_error=RuntimeError("boom"))
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)
        self.assertEqual(len(runner.capture_calls), 1)
        self.assertEqual(runner.check_calls, [])

    def test_capture_failure_does_not_retry(self):
        runner = FakeRunner(capture_error=IndeterminateReviewError("timeout"))
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)
        self.assertEqual(len(runner.capture_calls), 1)

    def test_check_failure_is_indeterminate_no_retry(self):
        runner = FakeRunner(check_errors={"diff_check": RuntimeError("boom")})
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)
        self.assertEqual(len(runner.capture_calls), 1)
        # diff_check falló antes de los siguientes.
        self.assertEqual(runner.check_calls, ["diff_check"])

    def test_check_failure_stops_remaining(self):
        runner = FakeRunner(check_errors={"git_status": IndeterminateReviewError("err")})
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)
        # git_status es el segundo en orden; diff_check corrió antes.
        self.assertEqual(runner.check_calls, ["diff_check", "git_status"])
        self.assertNotIn("unit_tests", runner.check_calls)

    def test_failed_check_status_is_not_error(self):
        # Un check que retorna fail es un resultado válido, no indeterminado.
        outcomes = {
            "diff_check": CheckOutcome("diff_check", "fail", "sha256:" + "c" * 64, 10),
            "git_status": CheckOutcome("git_status", "pass", "sha256:" + "d" * 64, 0),
            "unit_tests": CheckOutcome("unit_tests", "pass", "sha256:" + "e" * 64, 5),
        }
        runner = FakeRunner(check_outcomes=outcomes)
        evidence, state = _review(runner=runner)
        self.assertEqual(state, "REVIEWING")
        statuses = {c["check_id"]: c["status"] for c in evidence["checks"]}
        self.assertEqual(statuses["diff_check"], "fail")

    def test_indeterminate_does_not_duplicate(self):
        runner = FakeRunner(check_errors={"unit_tests": IndeterminateReviewError("x")})
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)
        self.assertEqual(runner.check_calls.count("unit_tests"), 1)


# ---------------------------------------------------------------------------
# Precálculo de transiciones y orden determinista.
# ---------------------------------------------------------------------------


class TransitionPrecalculationTests(unittest.TestCase):
    def test_source_precalculates_before_effects(self):
        # Las transiciones se calculan antes de capture_once.
        src = inspect.getsource(review_opencode_tmux)
        capture_pos = src.index("runner.capture_once")
        notify_pos = src.index('"notify"')
        review_pos = src.index('"review"')
        self.assertLess(notify_pos, capture_pos)
        self.assertLess(review_pos, capture_pos)

    def test_transitions_notify_then_review(self):
        from epistates.state import transition
        self.assertEqual(transition("WAITING_EXTERNAL", "notify"), "REVIEW_READY")
        self.assertEqual(transition("REVIEW_READY", "review"), "REVIEWING")


# ---------------------------------------------------------------------------
# Determinismo, reloj y polling.
# ---------------------------------------------------------------------------


class DeterminismAndClockTests(unittest.TestCase):
    def test_same_inputs_same_evidence(self):
        e1, _ = _review()
        e2, _ = _review()
        self.assertEqual(e1, e2)

    def test_injected_reviewed_at_affects_evidence(self):
        e1, _ = _review(reviewed_at="2026-08-11T18:45:00Z")
        e2, _ = _review(reviewed_at="2026-08-11T18:46:00Z")
        self.assertNotEqual(e1, e2)

    def test_source_reads_no_clock(self):
        self.assertNotIn("datetime.now", REVIEW_SRC)
        self.assertNotIn("datetime.utcnow", REVIEW_SRC)
        self.assertNotIn("time.time", REVIEW_SRC)
        self.assertNotIn("time.sleep", REVIEW_SRC)

    def test_source_has_no_subprocess(self):
        self.assertNotIn("subprocess", REVIEW_SRC)
        self.assertNotIn("os.system", REVIEW_SRC)

    def test_source_has_no_send_keys_or_capture_pane(self):
        self.assertNotIn("send-keys", REVIEW_SRC)
        self.assertNotIn("capture-pane", REVIEW_SRC)


# ---------------------------------------------------------------------------
# API cerrada.
# ---------------------------------------------------------------------------


class ClosedApiTests(unittest.TestCase):
    def test_orchestration_signature_has_no_argv_or_shell(self):
        params = inspect.signature(review_opencode_tmux).parameters
        for forbidden in ("argv", "cmd", "command_argv", "shell", "script", "args"):
            self.assertNotIn(forbidden, params, forbidden)


# ---------------------------------------------------------------------------
# review-evidence: validación estructural y binding.
# ---------------------------------------------------------------------------


class ReviewEvidenceValidatorTests(unittest.TestCase):
    def test_fixture_evidence_is_valid(self):
        validate_review_evidence(load("review-evidence-ok.json"))

    def test_fixture_evidence_binds(self):
        _bind()

    def test_unknown_field_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["extra"] = 1
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_missing_field_fails(self):
        evidence = load("review-evidence-ok.json")
        del evidence["human_notice_digest"]
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_wrong_phases_order_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["phases_confirmed"] = ["checks_once", "capture_once"]
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_wrong_final_state_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["final_state"] = "DONE"
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_wrong_confirms_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["confirms"] = "agent_understood"
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_unsorted_checks_fail(self):
        evidence = load("review-evidence-ok.json")
        evidence["checks"] = [
            {"check_id": "git_status", "status": "pass", "digest": "sha256:" + "a" * 64, "length_utf8": 0},
            {"check_id": "diff_check", "status": "pass", "digest": "sha256:" + "b" * 64, "length_utf8": 0},
        ]
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_duplicate_check_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["checks"] = [
            {"check_id": "git_status", "status": "pass", "digest": "sha256:" + "a" * 64, "length_utf8": 0},
            {"check_id": "git_status", "status": "fail", "digest": "sha256:" + "b" * 64, "length_utf8": 0},
        ]
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_bad_check_status_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["checks"][0]["status"] = "missing"
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_capture_lines_over_max_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["capture_lines"] = 201
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)

    def test_capture_lines_zero_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["capture_lines"] = 0
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)


class ReviewEvidenceBindingTests(unittest.TestCase):
    def test_built_evidence_roundtrips_through_binding(self):
        evidence, _ = _review()
        _bind(evidence=evidence)

    def test_wrong_task_card_digest_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["task_card_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_wrong_preflight_digest_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["preflight_result_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_wrong_dispatch_receipt_digest_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["dispatch_receipt_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_wrong_human_notice_digest_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["human_notice_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_auto_amplified_dispatch_policy_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["max_dispatch_age_seconds"] = 7200
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_auto_amplified_notice_policy_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["max_notice_age_seconds"] = 7200
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_expected_dispatch_policy_distinct_fails(self):
        with self.assertRaises(ValidationError):
            _bind(expected_dispatch_age=1800)

    def test_expected_notice_policy_distinct_fails(self):
        with self.assertRaises(ValidationError):
            _bind(expected_notice_age=1800)

    def test_wrong_message_fails(self):
        with self.assertRaises(ValidationError):
            _bind(message="mensaje distinto")

    def test_stale_reviewed_at_fails(self):
        evidence = load("review-evidence-ok.json")
        evidence["reviewed_at"] = "2026-08-11T20:00:00Z"
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_external_policy_rederives_freshness(self):
        # Igualdad a 7200 y reviewed 2h después de notified (7200s): en límite.
        notice = _notice()
        notice["notified_at"] = "2026-08-11T18:30:00Z"
        notice["max_dispatch_age_seconds"] = 7200
        from epistates.audit import canonical_digest
        evidence = load("review-evidence-ok.json")
        evidence["reviewed_at"] = "2026-08-11T20:30:00Z"
        evidence["max_dispatch_age_seconds"] = 7200
        evidence["max_notice_age_seconds"] = 7200
        evidence["human_notice_digest"] = canonical_digest(notice)
        _bind(evidence=evidence, notice=notice,
              expected_dispatch_age=7200, expected_notice_age=7200)

    # -- Corrección 1: binding de checks con igualdad exacta. ----------------

    def test_binding_rejects_missing_unit_tests_check(self):
        evidence = load("review-evidence-ok.json")
        # Quitar unit_tests del recibo.
        evidence["checks"] = [
            {"check_id": "diff_check", "status": "pass", "digest": "sha256:" + "b" * 64, "length_utf8": 0},
            {"check_id": "git_status", "status": "pass", "digest": "sha256:" + "c" * 64, "length_utf8": 0},
        ]
        with self.assertRaises(ValidationError):
            _bind(evidence=evidence)

    def test_binding_rejects_extra_check(self):
        evidence = load("review-evidence-ok.json")
        evidence["checks"].append(
            {"check_id": "git_status", "status": "pass", "digest": "sha256:" + "z" * 64, "length_utf8": 0}
        )
        with self.assertRaises(ValidationError):
            validate_review_evidence(evidence)  # duplicado atrapado por estructura.

    def test_binding_rejects_checks_not_matching_card(self):
        # La tarjeta requiere [diff_check, git_status, unit_tests]; el recibo
        # declara un conjunto distinto.
        evidence = load("review-evidence-ok.json")
        evidence["checks"] = [
            {"check_id": "diff_check", "status": "pass", "digest": "sha256:" + "b" * 64, "length_utf8": 0},
            {"check_id": "git_status", "status": "pass", "digest": "sha256:" + "c" * 64, "length_utf8": 0},
        ]
        with self.assertRaises(ValidationError) as exc:
            _bind(evidence=evidence)
        self.assertIn("coinciden exactamente", str(exc.exception))


# ---------------------------------------------------------------------------
# Corrección 6: fakes maliciosos — resultados inválidos tras efecto.
# ---------------------------------------------------------------------------


class MaliciousFakeOutcomeTests(unittest.TestCase):
    def test_malicious_capture_non_captureoutcome_is_indeterminate(self):
        runner = FakeRunner(capture_outcome="not-an-outcome")
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_malicious_capture_bad_digest_is_indeterminate(self):
        bad = CaptureOutcome(digest="not-a-digest", length_utf8=10, capture_lines=50)
        runner = FakeRunner(capture_outcome=bad)
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_malicious_capture_negative_length_is_indeterminate(self):
        bad = CaptureOutcome(digest="sha256:" + "a" * 64, length_utf8=-1, capture_lines=50)
        runner = FakeRunner(capture_outcome=bad)
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_malicious_capture_lines_out_of_range_is_indeterminate(self):
        bad = CaptureOutcome(digest="sha256:" + "a" * 64, length_utf8=10, capture_lines=999)
        runner = FakeRunner(capture_outcome=bad)
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_malicious_check_wrong_id_is_indeterminate(self):
        # El runner devuelve un CheckOutcome con check_id distinto al esperado.
        outcomes = {"diff_check": CheckOutcome("git_status", "pass", "sha256:" + "b" * 64, 0)}
        runner = FakeRunner(check_outcomes=outcomes)
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_malicious_check_bad_status_is_indeterminate(self):
        bad = CheckOutcome("unit_tests", "pass", "sha256:" + "b" * 64, 0)
        outcomes = {"unit_tests": bad}
        # Forzar un status inválido modificando el NamedTuple.
        bad_w = CheckOutcome("diff_check", "skipped", "sha256:" + "b" * 64, 0)
        outcomes2 = {"diff_check": bad_w}
        runner = FakeRunner(check_outcomes=outcomes2)
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_malicious_check_bad_digest_is_indeterminate(self):
        bad = CheckOutcome("diff_check", "pass", "evil", 0)
        runner = FakeRunner(check_outcomes={"diff_check": bad})
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_malicious_check_negative_length_is_indeterminate(self):
        bad = CheckOutcome("diff_check", "pass", "sha256:" + "b" * 64, -5)
        runner = FakeRunner(check_outcomes={"diff_check": bad})
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)

    def test_capture_was_attempted_before_malicious_detection(self):
        # La captura se intentó una vez; el resultado inválido no reintenta.
        bad = CaptureOutcome(digest="evil", length_utf8=10, capture_lines=50)
        runner = FakeRunner(capture_outcome=bad)
        with self.assertRaises(IndeterminateReviewError):
            _review(runner=runner)
        self.assertEqual(len(runner.capture_calls), 1)


# ---------------------------------------------------------------------------
# Replay: honestidad sobre unicidad global.
# ---------------------------------------------------------------------------


class ReplayHonestyTests(unittest.TestCase):
    def test_replay_with_advanced_state_blocks(self):
        # Tras la primera revisión el estado es REVIEWING. Un reintento con
        # current_state=REVIEWING se bloquea (review exige WAITING_EXTERNAL).
        runner = FakeRunner()
        with self.assertRaises(ReviewError):
            _review(runner=runner, current_state="REVIEWING")
        self.assertEqual(runner.capture_calls, [])

    def test_replay_with_waiting_external_is_not_detected(self):
        # Honestidad: un caller que mienta y vuelva a presentar WAITING_EXTERNAL
        # no puede detectarse aquí (stateless). La unicidad global exige
        # persistencia externa. La función no mantiene estado mutable entre
        # llamadas: las mismas entradas producen la misma evidencia.
        e1, _ = _review()
        e2, _ = _review()
        self.assertEqual(e1, e2)


if __name__ == "__main__":
    unittest.main()
