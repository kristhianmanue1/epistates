"""Contrato puro para resultados de auditoría; no obtiene ni ejecuta evidencia."""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import ValidationError
from .contracts import validate_task_card


_REQUIRED_TOP_LEVEL = {
    "schema", "task_id", "run_id", "attempt_id", "task_card_digest",
    "authority_binding", "observed_at", "state_before", "classification",
    "decision", "evidence",
}
# ``review_evidence_digest`` es una AMPLIACIÓN PRE-RELEASE del contrato
# ``audit-result/v1`` (Slice5). **No** es "version-compatible": un validador
# v1 anterior a Slice5 rechaza este campo como desconocido. El validador nuevo
# sigue aceptando artefactos H2 (lectura de artefactos H2 por el validador
# nuevo), pero los artefactos bridge NO son aceptados por validadores v1
# anteriores. Véase ``docs/plan-inicial.md`` (Contrato H3 — Slice5).
_OPTIONAL_TOP_LEVEL = {"review_evidence_digest"}
_TOP_LEVEL = _REQUIRED_TOP_LEVEL | _OPTIONAL_TOP_LEVEL
_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_UTC_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z")
# ``capture`` se añade como evidence_id cerrado para representar la captura de
# ``review-evidence/v1`` mediante un digest verificable (Slice5). Es una
# ampliación pre-release: el validador estructural impone que ``capture`` y
# ``review_evidence_digest`` son bidireccionalmente requeridos (no se puede
# downgradear un artefacto bridge a H2 eliminando un solo campo).
_EVIDENCE_IDS = {"git_status", "diff_check", "unit_tests", "file_digest", "capture"}
_EVIDENCE_STATES = {"pass", "fail", "missing"}
_OUTCOMES = {
    ("OK", "proceed"): "DONE",
    ("PARCIAL", "fix-and-retry"): "CORRECTION_SENT",
    ("PARCIAL", "escalate"): "BLOCKED",
    ("BLOQ", "escalate"): "BLOCKED",
}


def _require_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe usar minúsculas, dígitos o guiones")


def _require_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe ser sha256:<64 hex>")


def _require_utc_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not _UTC_PATTERN.fullmatch(value):
        raise ValidationError("observed_at debe ser RFC3339 UTC terminado en Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValidationError("observed_at debe ser RFC3339 UTC válido") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValidationError("observed_at debe estar en UTC")


def validate_audit_result(result: Mapping[str, Any]) -> None:
    """Valida coherencia interna sin confiar en la procedencia declarada."""
    if not isinstance(result, Mapping):
        raise ValidationError("el resultado debe ser un objeto JSON")
    missing = _REQUIRED_TOP_LEVEL - result.keys()
    unknown = result.keys() - _TOP_LEVEL
    if missing:
        raise ValidationError(f"campos requeridos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise ValidationError(f"campos no permitidos: {rendered}")
    if "review_evidence_digest" in result:
        _require_digest(result["review_evidence_digest"], "review_evidence_digest")
    if result["schema"] != "epistates/audit-result/v1":
        raise ValidationError("schema debe ser epistates/audit-result/v1")
    for field in ("task_id", "run_id", "attempt_id"):
        _require_id(result[field], field)
    _require_digest(result["task_card_digest"], "task_card_digest")
    authority = result["authority_binding"]
    if not isinstance(authority, Mapping) or set(authority) != {"grant_id", "grant_digest", "decision_reference"}:
        raise ValidationError("authority_binding debe declarar grant_id, grant_digest y decision_reference")
    _require_id(authority["grant_id"], "authority_binding.grant_id")
    _require_digest(authority["grant_digest"], "authority_binding.grant_digest")
    _require_id(authority["decision_reference"], "authority_binding.decision_reference")
    _require_utc_timestamp(result["observed_at"])
    if result["state_before"] != "REVIEWING":
        raise ValidationError("state_before debe ser REVIEWING")
    classification = result["classification"]
    decision = result["decision"]
    if not isinstance(classification, str) or not isinstance(decision, str):
        raise ValidationError("classification y decision deben ser texto soportado")
    outcome = (classification, decision)
    if outcome not in _OUTCOMES:
        raise ValidationError("combinación classification/decision no permitida")
    evidence = result["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValidationError("evidence debe ser una lista no vacía")
    seen = set()
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"evidence_id", "status", "digest"}:
            raise ValidationError("cada evidencia debe contener evidence_id, status y digest")
        evidence_id = item["evidence_id"]
        status = item["status"]
        if not isinstance(evidence_id, str) or evidence_id not in _EVIDENCE_IDS:
            raise ValidationError("evidence_id no está en el catálogo")
        if evidence_id in seen:
            raise ValidationError("evidence_id duplicado")
        seen.add(evidence_id)
        if not isinstance(status, str) or status not in _EVIDENCE_STATES:
            raise ValidationError("status de evidencia no soportado")
        if status == "missing":
            if item["digest"] is not None:
                raise ValidationError("evidencia missing debe usar digest null")
        else:
            _require_digest(item["digest"], "evidence[].digest")
    if result["classification"] == "OK" and any(item["status"] != "pass" for item in evidence):
        raise ValidationError("OK exige toda la evidencia en pass")
    # Bidireccionalidad bridge: ``capture`` y ``review_evidence_digest`` se
    # requieren mutuamente. Impide el downgrade de un artefacto bridge a H2
    # eliminando un solo campo (p. ej. sólo ``review_evidence_digest`` manteniendo
    # ``capture``). El loop anterior ya rechaza ``capture`` duplicado, así que
    # ``"capture" in seen`` implica exactamente una entrada capture.
    has_capture = "capture" in seen
    has_review_digest = "review_evidence_digest" in result
    if has_capture and not has_review_digest:
        raise ValidationError(
            "evidence_id capture exige review_evidence_digest "
            "(no se puede downgradear un artefacto bridge)"
        )
    if has_review_digest and not has_capture:
        raise ValidationError(
            "review_evidence_digest exige exactamente una evidencia capture"
        )


def canonical_digest(value: Mapping[str, Any]) -> str:
    """Calcula la huella canónica de un objeto JSON ya validado."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_audit_binding(
    result: Mapping[str, Any], task_card: Mapping[str, Any],
    expected_run_id: str, expected_attempt_id: str,
) -> None:
    """Liga resultado, tarjeta, grant y evidencia exigida sin efectos laterales."""
    validate_audit_result(result)
    validate_task_card(task_card)
    if result["task_id"] != task_card["task_id"]:
        raise ValidationError("task_id no coincide con la tarjeta")
    _require_id(expected_run_id, "expected_run_id")
    _require_id(expected_attempt_id, "expected_attempt_id")
    if result["run_id"] != expected_run_id:
        raise ValidationError("run_id no coincide con el contexto esperado")
    if result["attempt_id"] != expected_attempt_id:
        raise ValidationError("attempt_id no coincide con el contexto esperado")
    if result["task_card_digest"] != canonical_digest(task_card):
        raise ValidationError("task_card_digest no coincide con la tarjeta")
    authority = task_card["authority"]
    binding = result["authority_binding"]
    if binding["grant_id"] != authority["grant_id"]:
        raise ValidationError("grant_id no coincide con la tarjeta")
    if binding["grant_digest"] != canonical_digest(authority):
        raise ValidationError("grant_digest no coincide con la autoridad de la tarjeta")
    required = {check["check_id"] for check in task_card["checks"]}
    evidence_map = {
        "worktree_status": {"git_status"},
        "diff_check": {"diff_check"},
        "check_results": {check["check_id"] for check in task_card["checks"]},
    }
    for requirement in task_card["evidence"]["required"]:
        required.update(evidence_map[requirement])
    observed = {item["evidence_id"] for item in result["evidence"]}
    missing = required - observed
    if missing:
        raise ValidationError(f"evidencia requerida ausente: {', '.join(sorted(missing))}")


def _state_after_audit(
    result: Mapping[str, Any], task_card: Mapping[str, Any],
    expected_run_id: str, expected_attempt_id: str,
) -> str:
    """Deriva el estado para la API de transición después de bindings exactos."""
    validate_audit_binding(result, task_card, expected_run_id, expected_attempt_id)
    return _OUTCOMES[(result["classification"], result["decision"])]
