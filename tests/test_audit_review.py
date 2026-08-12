import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from epistates.audit import canonical_digest, validate_audit_result
from epistates.audit_review import (
    AuditReviewError,
    _MAX_AUDIT_AGE_CEILING,
    _OUTCOMES,
    _derive_audit_evidence_from_review,
    apply_audit_from_review,
    validate_audit_review_binding,
)
from epistates.contracts import ValidationError


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
DECISION_REF = "conversation-2026-08-11"
# observed_at del fixture; reviewed_at de review-evidence es 18:45:00Z.
OBSERVED_AT = "2026-08-11T19:00:00Z"
MAX_AUDIT_AGE = 3600
GRANT_ID = "maintainer-e1-contracts"
GRANT_DIGEST = "sha256:24a39dff4b7a38f45959b89850debed2bb584fb4c887278748064ed6f1eda2cd"


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


def _evidence():
    return load("review-evidence-ok.json")


def _build_audit_result(
    *,
    classification="OK",
    decision="proceed",
    decision_reference=DECISION_REF,
    observed_at="2026-08-11T19:00:00Z",
    evidence_override=None,
    review_evidence=None,
):
    """Construye un audit-result coherente con review-evidence-ok.json."""
    if review_evidence is None:
        review_evidence = _evidence()
    evidence = evidence_override
    if evidence is None:
        evidence = _derive_audit_evidence_from_review(review_evidence)
    return {
        "schema": "epistates/audit-result/v1",
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "task_card_digest": canonical_digest(_task()),
        "authority_binding": {
            "grant_id": _task()["authority"]["grant_id"],
            "grant_digest": canonical_digest(_task()["authority"]),
            "decision_reference": decision_reference,
        },
        "observed_at": observed_at,
        "state_before": "REVIEWING",
        "classification": classification,
        "decision": decision,
        "review_evidence_digest": canonical_digest(review_evidence),
        "evidence": evidence,
    }


def _binding_kwargs(**overrides):
    kwargs = dict(
        expected_run_id=RUN_ID,
        expected_attempt_id=ATTEMPT_ID,
        expected_session_name=SESSION,
        expected_command=COMMAND,
        expected_max_preflight_age_seconds=MAX_PREFLIGHT_AGE,
        message=MESSAGE,
        expected_max_dispatch_age_seconds=MAX_DISPATCH_AGE,
        expected_max_notice_age_seconds=MAX_NOTICE_AGE,
        expected_classification="OK",
        expected_decision="proceed",
        expected_decision_reference=DECISION_REF,
        expected_observed_at=OBSERVED_AT,
        max_audit_age_seconds=MAX_AUDIT_AGE,
        expected_grant_id=GRANT_ID,
        expected_grant_digest=GRANT_DIGEST,
    )
    kwargs.update(overrides)
    return kwargs


def _bind(audit_result=None, review_evidence=None, **overrides):
    if audit_result is None:
        audit_result = _build_audit_result(review_evidence=review_evidence)
    if review_evidence is None:
        review_evidence = _evidence()
    kwargs = _binding_kwargs(**overrides)
    validate_audit_review_binding(
        audit_result, review_evidence, _task(), _adapter(),
        _preflight(), _receipt(), _notice(),
        **kwargs,
    )


def _apply(audit_result=None, review_evidence=None, current_state="REVIEWING", **overrides):
    if audit_result is None:
        audit_result = _build_audit_result(review_evidence=review_evidence)
    if review_evidence is None:
        review_evidence = _evidence()
    kwargs = _binding_kwargs(**overrides)
    return apply_audit_from_review(
        audit_result, review_evidence, _task(), _adapter(),
        _preflight(), _receipt(), _notice(),
        current_state=current_state, **kwargs,
    )


# ---------------------------------------------------------------------------
# Derivación de evidencia desde review-evidence.
# ---------------------------------------------------------------------------


class DeriveEvidenceTests(unittest.TestCase):
    def test_checks_copied_in_review_order_then_capture(self):
        ev = _evidence()
        derived = _derive_audit_evidence_from_review(ev)
        # Tres checks en el orden de review-evidence (sorted by check_id) + capture.
        self.assertEqual(len(derived), 4)
        self.assertEqual(
            [i["evidence_id"] for i in derived[:3]],
            [c["check_id"] for c in ev["checks"]],
        )
        self.assertEqual(derived[3]["evidence_id"], "capture")
        self.assertEqual(derived[3]["status"], "pass")
        self.assertEqual(derived[3]["digest"], ev["capture_digest"])

    def test_check_status_and_digest_copied_exactly(self):
        ev = _evidence()
        derived = _derive_audit_evidence_from_review(ev)
        for src, dst in zip(ev["checks"], derived[:3]):
            self.assertEqual(dst["evidence_id"], src["check_id"])
            self.assertEqual(dst["status"], src["status"])
            self.assertEqual(dst["digest"], src["digest"])


# ---------------------------------------------------------------------------
# Binding: casos válidos.
# ---------------------------------------------------------------------------


class ValidBindingTests(unittest.TestCase):
    def test_programmatic_audit_result_binds(self):
        _bind()

    def test_fixture_audit_result_binds(self):
        audit = load("audit-result-review-bound.json")
        # El fixture debe tener el digest correcto; este test lo verifica.
        expected_digest = canonical_digest(_evidence())
        self.assertEqual(
            audit["review_evidence_digest"], expected_digest,
            "el fixture audit-result-review-bound.json tiene un review_evidence_digest "
            "desactualizado; debe ser " + expected_digest,
        )
        _bind(audit_result=audit)


# ---------------------------------------------------------------------------
# Semántica de transiciones (sólo las 4 combinaciones del ADR-0001).
# ---------------------------------------------------------------------------


class TransitionSemanticsTests(unittest.TestCase):
    def test_ok_proceed_reaches_done(self):
        audit = _build_audit_result()
        result, state = _apply(audit)
        self.assertIs(result, audit)
        self.assertEqual(state, "DONE")

    def test_parcial_fix_and_retry_reaches_correction_sent(self):
        # Forzamos un check fail para que PARCIAL sea coherente con la evidencia.
        ev = _evidence()
        ev = json.loads(json.dumps(ev))
        ev["checks"][0]["status"] = "fail"
        audit = _build_audit_result(
            classification="PARCIAL", decision="fix-and-retry",
            review_evidence=ev,
        )
        _, state = _apply(audit, review_evidence=ev,
                          expected_classification="PARCIAL",
                          expected_decision="fix-and-retry")
        self.assertEqual(state, "CORRECTION_SENT")

    def test_parcial_escalate_reaches_blocked(self):
        ev = json.loads(json.dumps(_evidence()))
        ev["checks"][0]["status"] = "fail"
        audit = _build_audit_result(
            classification="PARCIAL", decision="escalate",
            review_evidence=ev,
        )
        _, state = _apply(audit, review_evidence=ev,
                          expected_classification="PARCIAL",
                          expected_decision="escalate")
        self.assertEqual(state, "BLOCKED")

    def test_bloq_escalate_reaches_blocked(self):
        ev = json.loads(json.dumps(_evidence()))
        for c in ev["checks"]:
            c["status"] = "fail"
        audit = _build_audit_result(
            classification="BLOQ", decision="escalate",
            review_evidence=ev,
        )
        _, state = _apply(audit, review_evidence=ev,
                          expected_classification="BLOQ",
                          expected_decision="escalate")
        self.assertEqual(state, "BLOCKED")

    def test_no_extra_combinations_allowed(self):
        # El catálogo de combinaciones es exactamente las 4 del ADR-0001.
        self.assertEqual(_OUTCOMES, frozenset({
            ("OK", "proceed"),
            ("PARCIAL", "fix-and-retry"),
            ("PARCIAL", "escalate"),
            ("BLOQ", "escalate"),
        }))


# ---------------------------------------------------------------------------
# Estado: sólo desde REVIEWING.
# ---------------------------------------------------------------------------


class StateGuardTests(unittest.TestCase):
    def test_requires_reviewing_state(self):
        audit = _build_audit_result()
        for bad in ("PREPARED", "DISPATCHED", "WAITING_EXTERNAL",
                    "REVIEW_READY", "CORRECTION_SENT", "DONE", "BLOCKED"):
            with self.assertRaises(AuditReviewError, msg=bad):
                _apply(audit, current_state=bad)


# ---------------------------------------------------------------------------
# Adversarial: review-evidence con digest distinto / misbound.
# ---------------------------------------------------------------------------


class ReviewEvidenceMismatchTests(unittest.TestCase):
    def test_review_evidence_digest_mismatch_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["review_evidence_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_review_evidence_digest_missing_fails_closed(self):
        audit = _build_audit_result()
        del audit["review_evidence_digest"]
        # El validador estructural lo rechaza primero (bidireccionalidad
        # capture <-> review_evidence_digest): no se puede downgradear.
        with self.assertRaises(ValidationError) as exc:
            _bind(audit_result=audit)
        self.assertIn("capture exige review_evidence_digest", str(exc.exception))

    def test_review_evidence_different_by_capture_digest_fails_closed(self):
        # review-evidence con capture_digest alterado: su digest cambia y ya no
        # liga con el audit-result que referencia al review-evidence original.
        ev = json.loads(json.dumps(_evidence()))
        ev["capture_digest"] = "sha256:" + "9" * 64
        audit = _build_audit_result()  # referenciado al evidence original
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, review_evidence=ev)


# ---------------------------------------------------------------------------
# Adversarial: checks omitidos / extra / reordenados.
# ---------------------------------------------------------------------------


class CheckExactMatchTests(unittest.TestCase):
    def test_omitted_check_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        # Quita unit_tests del audit-result.
        audit["evidence"] = [i for i in audit["evidence"] if i["evidence_id"] != "unit_tests"]
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_extra_check_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["evidence"].append({
            "evidence_id": "file_digest", "status": "pass",
            "digest": "sha256:" + "f" * 64,
        })
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_reordered_checks_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        # Intercambia el primer y segundo check (rompe el orden de review-evidence).
        audit["evidence"][0], audit["evidence"][1] = audit["evidence"][1], audit["evidence"][0]
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_capture_omitted_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["evidence"] = [i for i in audit["evidence"] if i["evidence_id"] != "capture"]
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_capture_digest_changed_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        for i in audit["evidence"]:
            if i["evidence_id"] == "capture":
                i["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_check_status_changed_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        # Cambia git_status de pass a fail sin cambiar review-evidence.
        for i in audit["evidence"]:
            if i["evidence_id"] == "git_status":
                i["status"] = "fail"
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_check_digest_changed_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        for i in audit["evidence"]:
            if i["evidence_id"] == "diff_check":
                i["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)


# ---------------------------------------------------------------------------
# Adversarial: OK con check fail (no puede producir OK/proceed/DONE).
# ---------------------------------------------------------------------------


class OkWithFailTests(unittest.TestCase):
    def test_ok_with_failing_check_fails_closed(self):
        # review-evidence con un check fail; el audit-result reclama OK/proceed.
        ev = json.loads(json.dumps(_evidence()))
        ev["checks"][0]["status"] = "fail"
        audit = _build_audit_result(
            classification="OK", decision="proceed", review_evidence=ev,
        )
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, review_evidence=ev)

    def test_ok_with_failing_check_rejected_at_apply(self):
        ev = json.loads(json.dumps(_evidence()))
        ev["checks"][0]["status"] = "fail"
        audit = _build_audit_result(
            classification="OK", decision="proceed", review_evidence=ev,
        )
        with self.assertRaises(AuditReviewError):
            _apply(audit, review_evidence=ev)


# ---------------------------------------------------------------------------
# Adversarial: decisión / reference / authority esperada incorrecta.
# ---------------------------------------------------------------------------


class DecisionMismatchTests(unittest.TestCase):
    def test_classification_mismatch_fails_closed(self):
        audit = _build_audit_result(classification="OK", decision="proceed")
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_classification="PARCIAL")

    def test_decision_mismatch_fails_closed(self):
        audit = _build_audit_result(classification="PARCIAL", decision="escalate",
                                    review_evidence=_failing_evidence())
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, review_evidence=_failing_evidence(),
                  expected_classification="PARCIAL", expected_decision="fix-and-retry")

    def test_decision_reference_mismatch_fails_closed(self):
        audit = _build_audit_result(decision_reference="conversation-2026-08-11")
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_decision_reference="other-reference")

    def test_unknown_outcome_combination_fails_closed(self):
        # BLOQ + proceed no está permitido; el structural validator lo rechaza.
        ev = _failing_evidence()
        audit = _build_audit_result(
            classification="BLOQ", decision="proceed", review_evidence=ev,
        )
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, review_evidence=ev,
                  expected_classification="BLOQ", expected_decision="proceed")


def _failing_evidence():
    ev = json.loads(json.dumps(_evidence()))
    for c in ev["checks"]:
        c["status"] = "fail"
    return ev


# ---------------------------------------------------------------------------
# Adversarial: run/attempt/task/card/policies/timestamps misbound.
# ---------------------------------------------------------------------------


class ChainMisbindTests(unittest.TestCase):
    def test_misbound_run_id_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind(expected_run_id="run-999")

    def test_misbound_attempt_id_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind(expected_attempt_id="attempt-999")

    def test_misbound_task_card_digest_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["task_card_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_misbound_grant_digest_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["authority_binding"]["grant_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_misbound_grant_id_fails_closed(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["authority_binding"]["grant_id"] = "other-grant-id"
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit)

    def test_misbound_session_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind(expected_session_name="other-session")

    def test_misbound_command_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind(expected_command="wrong-command")

    def test_misbound_dispatch_policy_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind(expected_max_dispatch_age_seconds=1800)

    def test_misbound_notice_policy_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind(expected_max_notice_age_seconds=1800)

    def test_misbound_message_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind(message="mensaje distinto")

    def test_misbound_dispatch_receipt_digest_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind_via_receipt()

    def test_misbound_human_notice_digest_fails_closed(self):
        with self.assertRaises(ValidationError):
            _bind_via_notice()


def _bind_via_receipt():
    # Construye un binding donde el dispatch receipt está mal ligado.
    receipt = json.loads(json.dumps(_receipt()))
    receipt["preflight_result_digest"] = "sha256:" + "0" * 64
    ev = _evidence()
    audit = _build_audit_result()
    kwargs = _binding_kwargs()
    validate_audit_review_binding(
        audit, ev, _task(), _adapter(), _preflight(), receipt, _notice(), **kwargs,
    )


def _bind_via_notice():
    notice = json.loads(json.dumps(_notice()))
    notice["dispatch_receipt_digest"] = "sha256:" + "0" * 64
    ev = _evidence()
    audit = _build_audit_result()
    kwargs = _binding_kwargs()
    validate_audit_review_binding(
        audit, ev, _task(), _adapter(), _preflight(), _receipt(), notice, **kwargs,
    )


# ---------------------------------------------------------------------------
# Adversarial: review-evidence con check cambiado (status/digest) rebota al
# audit-result vía match exacto.
# ---------------------------------------------------------------------------


class ReviewEvidenceCheckChangedTests(unittest.TestCase):
    def test_review_check_status_changed_rejects_audit_result(self):
        # review-evidence dice git_status=fail; audit-result dice pass.
        ev = json.loads(json.dumps(_evidence()))
        for c in ev["checks"]:
            if c["check_id"] == "git_status":
                c["status"] = "fail"
        audit = _build_audit_result()  # evidencia original (pass)
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, review_evidence=ev)


# ---------------------------------------------------------------------------
# Pureza: sin subprocess, sin reloj, sin efectos.
# ---------------------------------------------------------------------------


class PurityTests(unittest.TestCase):
    def test_source_has_no_subprocess(self):
        src = inspect.getsource(validate_audit_review_binding) + inspect.getsource(apply_audit_from_review)
        self.assertNotIn("subprocess", src)
        self.assertNotIn("os.system", src)

    def test_source_reads_no_clock(self):
        src = inspect.getsource(validate_audit_review_binding) + inspect.getsource(apply_audit_from_review)
        self.assertNotIn("datetime.now", src)
        self.assertNotIn("datetime.utcnow", src)
        self.assertNotIn("time.time", src)
        self.assertNotIn("time.sleep", src)

    def test_apply_returns_input_audit_result(self):
        audit = _build_audit_result()
        result, state = _apply(audit)
        self.assertIs(result, audit)
        self.assertEqual(state, "DONE")


# ---------------------------------------------------------------------------
# Hacia atrás: H2 audit-result (sin campos bridge) sigue siendo válido.
# ---------------------------------------------------------------------------


class H2BackwardCompatTests(unittest.TestCase):
    def test_h2_audit_result_without_bridge_fields_is_structurally_valid(self):
        h2 = load("audit-result-valid.json")
        self.assertNotIn("review_evidence_digest", h2)
        validate_audit_result(h2)

    def test_h2_audit_result_binding_still_works(self):
        from epistates.audit import validate_audit_binding
        h2 = load("audit-result-valid.json")
        validate_audit_binding(h2, _task(), RUN_ID, ATTEMPT_ID)


# ---------------------------------------------------------------------------
# Corrección 1: política externa de timestamp (anti-futuro autodeclarado).
# ---------------------------------------------------------------------------


class TimestampPolicyTests(unittest.TestCase):
    def test_future_observed_at_rejected(self):
        # Reproducción del informe: observed_at en el futuro era aceptado.
        audit = _build_audit_result(observed_at="2099-01-01T00:00:00Z")
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_observed_at="2099-01-01T00:00:00Z")

    def test_observed_at_mismatch_with_expected_rejected(self):
        audit = _build_audit_result()  # observed_at = 19:00:00Z
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_observed_at="2026-08-11T19:01:00Z")

    def test_observed_at_preceding_reviewed_at_rejected(self):
        # reviewed_at = 18:45:00Z; observed_at anterior es imposible.
        audit = _build_audit_result(observed_at="2026-08-11T18:00:00Z")
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_observed_at="2026-08-11T18:00:00Z")

    def test_stale_observed_at_rejected(self):
        # delta > max_audit_age_seconds (reviewed 18:45, observed 20:30 = 6300s).
        audit = _build_audit_result(observed_at="2026-08-11T20:30:00Z")
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_observed_at="2026-08-11T20:30:00Z",
                  max_audit_age_seconds=3600)

    def test_boundary_observed_at_accepted(self):
        # reviewed 18:45, observed 19:45 = 3600s == max 3600: boundary OK (<=).
        audit = _build_audit_result(observed_at="2026-08-11T19:45:00Z")
        _bind(audit_result=audit, expected_observed_at="2026-08-11T19:45:00Z",
              max_audit_age_seconds=3600)

    def test_boundary_plus_one_rejected(self):
        audit = _build_audit_result(observed_at="2026-08-11T19:45:01Z")
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_observed_at="2026-08-11T19:45:01Z",
                  max_audit_age_seconds=3600)

    def test_bad_observed_at_policy_nan_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(max_audit_age_seconds=float("nan"))

    def test_bad_observed_at_policy_inf_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(max_audit_age_seconds=float("inf"))

    def test_bad_observed_at_policy_zero_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(max_audit_age_seconds=0)

    def test_bad_observed_at_policy_negative_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(max_audit_age_seconds=-5)

    def test_bad_observed_at_policy_boolean_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(max_audit_age_seconds=True)

    def test_bad_observed_at_policy_over_ceiling_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(max_audit_age_seconds=_MAX_AUDIT_AGE_CEILING + 1)

    def test_malformed_expected_observed_at_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(expected_observed_at="2026-08-11 19:00:00Z")


# ---------------------------------------------------------------------------
# Corrección 2: autoridad externa inyectada (no autodeclarada por el JSON).
# ---------------------------------------------------------------------------


class ExternalAuthorityTests(unittest.TestCase):
    def test_wrong_external_grant_id_rejected(self):
        # El controlador inyecta un grant_id distinto: falla aunque los
        # artefactos sean internamente coherentes entre sí.
        with self.assertRaises(ValidationError):
            _bind(expected_grant_id="other-grant-id")

    def test_wrong_external_grant_digest_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(expected_grant_digest="sha256:" + "0" * 64)

    def test_external_grant_id_mismatching_task_card_rejected(self):
        # El grant externo no coincide con la tarjeta: falla cerrado.
        with self.assertRaises(ValidationError):
            _bind(expected_grant_id="some-other-grant",
                  expected_grant_digest="sha256:" + "0" * 64)

    def test_external_grant_digest_mismatching_task_card_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(expected_grant_digest="sha256:" + "1" * 64)

    def test_malformed_external_grant_id_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(expected_grant_id="UPPER-CASE")

    def test_malformed_external_grant_digest_rejected(self):
        with self.assertRaises(ValidationError):
            _bind(expected_grant_digest="not-a-digest")

    def test_self_declared_grant_in_audit_result_rejected(self):
        # El audit-result declara un grant_id distinto del externo: rechazado
        # aunque coincida con la tarjeta (correlación != autoridad actual).
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["authority_binding"]["grant_id"] = "maintainer-e1-contracts"
        # Mismo valor que la tarjeta, pero el externo inyectado difiere:
        with self.assertRaises(ValidationError):
            _bind(audit_result=audit, expected_grant_id="controller-injected-grant",
                  expected_grant_digest="sha256:" + "0" * 64)


# ---------------------------------------------------------------------------
# Corrección 3: downgrade por presencia (bidireccionalidad estructural).
# ---------------------------------------------------------------------------


class DowngradePreventionTests(unittest.TestCase):
    def test_capture_without_review_evidence_digest_rejected_structurally(self):
        audit = _build_audit_result()
        del audit["review_evidence_digest"]
        with self.assertRaises(ValidationError) as exc:
            validate_audit_result(audit)
        self.assertIn("capture exige review_evidence_digest", str(exc.exception))

    def test_review_evidence_digest_without_capture_rejected_structurally(self):
        audit = _build_audit_result()
        audit = json.loads(json.dumps(audit))
        audit["evidence"] = [i for i in audit["evidence"] if i["evidence_id"] != "capture"]
        with self.assertRaises(ValidationError) as exc:
            validate_audit_result(audit)
        self.assertIn("review_evidence_digest exige exactamente una evidencia capture",
                      str(exc.exception))

    def test_legacy_apply_audit_cannot_bypass_bridge_downgrade(self):
        # Reproducción del informe: eliminar sólo review_evidence_digest y usar
        # apply_audit legado producía DONE. Ahora el estructural lo impide.
        from epistates.audit import validate_audit_binding
        audit = _build_audit_result()
        del audit["review_evidence_digest"]
        with self.assertRaises(ValidationError):
            validate_audit_binding(audit, _task(), RUN_ID, ATTEMPT_ID)

    def test_pure_h2_artifact_without_bridge_fields_still_valid(self):
        # Remover TODOS los campos bridge produce un artefacto H2 distinto y
        # válido (documentado: el host H3 debe usar apply_audit_from_review).
        h2 = {
            "schema": "epistates/audit-result/v1",
            "task_id": TASK_ID, "run_id": RUN_ID, "attempt_id": ATTEMPT_ID,
            "task_card_digest": canonical_digest(_task()),
            "authority_binding": {
                "grant_id": GRANT_ID, "grant_digest": GRANT_DIGEST,
                "decision_reference": DECISION_REF,
            },
            "observed_at": OBSERVED_AT, "state_before": "REVIEWING",
            "classification": "OK", "decision": "proceed",
            "evidence": [
                {"evidence_id": "git_status", "status": "pass", "digest": "sha256:" + "c" * 64},
                {"evidence_id": "diff_check", "status": "pass", "digest": "sha256:" + "b" * 64},
                {"evidence_id": "unit_tests", "status": "pass", "digest": "sha256:" + "d" * 64},
            ],
        }
        validate_audit_result(h2)


# ---------------------------------------------------------------------------
# Corrección 5: cero llamadas a apply_audit cuando falla timestamp, política o
# autoridad externa (validación antes del efecto).
# ---------------------------------------------------------------------------


class ZeroApplyAuditOnFailureTests(unittest.TestCase):
    def _apply_with_mocked_state(self, **overrides):
        """Ejecuta _apply parcheando apply_audit; devuelve (call_count, raised)."""
        with patch("epistates.audit_review.apply_audit") as mocked:
            try:
                _apply(**overrides)
            except (AuditReviewError, ValidationError):
                return mocked.call_count, True
            return mocked.call_count, False

    def test_timestamp_mismatch_makes_zero_apply_calls(self):
        count, raised = self._apply_with_mocked_state(
            expected_observed_at="2026-08-11T19:01:00Z",
        )
        self.assertTrue(raised)
        self.assertEqual(count, 0)

    def test_bad_audit_policy_makes_zero_apply_calls(self):
        count, raised = self._apply_with_mocked_state(
            max_audit_age_seconds=0,
        )
        self.assertTrue(raised)
        self.assertEqual(count, 0)

    def test_wrong_external_grant_makes_zero_apply_calls(self):
        count, raised = self._apply_with_mocked_state(
            expected_grant_id="other-grant",
        )
        self.assertTrue(raised)
        self.assertEqual(count, 0)

    def test_stale_observed_at_makes_zero_apply_calls(self):
        audit = _build_audit_result(observed_at="2026-08-11T20:30:00Z")
        with patch("epistates.audit_review.apply_audit") as mocked:
            try:
                _apply(audit_result=audit,
                       expected_observed_at="2026-08-11T20:30:00Z",
                       max_audit_age_seconds=3600)
            except (AuditReviewError, ValidationError):
                raised = True
            else:
                raised = False
        self.assertTrue(raised)
        self.assertEqual(mocked.call_count, 0)

    def test_wrong_state_makes_zero_apply_calls(self):
        count, raised = self._apply_with_mocked_state(current_state="REVIEW_READY")
        self.assertTrue(raised)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
