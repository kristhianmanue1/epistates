"""Puente ``review-evidence/v1`` -> ``audit-result/v1`` -> ``apply_audit``.

Cierra el ciclo de auditoría ligando un ``review-evidence/v1`` válido y su cadena
completa al ``audit-result/v1`` exacto **antes** de aplicar una transición. Es
puro: no lanza procesos externos, no lee el reloj, no escribe estado ni archivos.

Ampliación pre-release del contrato (Slice5)
--------------------------------------------

Este puente es una **ampliación pre-release** de ``audit-result/v1``: añade
``review_evidence_digest`` y ``capture`` al catálogo. **No** es "version-
compatible": los artefactos bridge NO son aceptados por validadores v1 anteriores
a Slice5 (rechazan ``review_evidence_digest`` como campo desconocido). El
validador nuevo sigue aceptando artefactos H2 puros (sin campos bridge). El host
H3 debe usar exclusivamente ``apply_audit_from_review``; el ``apply_audit``
legado de H2 **no** es equivalente y no cierra la cadena review-evidence.

Separación de responsabilidades
-------------------------------

- ``review`` inspecciona (read-only) y produce ``review-evidence/v1``.
- ``audit`` valida la forma y el binding H2 de ``audit-result/v1``.
- Este módulo **liga** el audit-result al review-evidence exacto y aplica la
  transición. Reutiliza los validadores existentes; no duplica reglas.

Evidencia derivada exclusivamente desde review-evidence
-------------------------------------------------------

- Todos los checks requeridos deben coincidir **exactamente** en
  identidad/status/digest con los de ``review-evidence``: ni omitidos, ni extra,
  ni reordenados.
- La captura queda representada mediante un ``evidence_id`` cerrado
  (``capture``) y su digest verificable (``capture_digest``).

Decisión y autoridad inyectadas, no autodeclaradas
--------------------------------------------------

- ``classification``, ``decision`` y ``authority_binding.decision_reference`` no
  se derivan de exit codes ni los declara el ejecutor: llegan como decisión
  explícita inyectada por el controlador/mantenedor y se validan contra
  parámetros externos esperados (anti-auto-amplificación).
- ``authority_binding.grant_id`` y ``authority_binding.grant_digest`` se validan
  contra ``expected_grant_id``/``expected_grant_digest`` externos (que a su vez
  deben coincidir con la tarjeta): el grant de la tarjeta es correlación, no
  autoridad actual. Un JSON no puede elegir su propia autoridad.
- ``observed_at`` se valida contra ``expected_observed_at`` exacto y una ventana
  ``max_audit_age_seconds`` externa (finita, positiva, con techo duro): exige
  ``observed_at >= review_evidence.reviewed_at`` y delta <= política. No se lee
  el reloj.
- Un review con cualquier check ``fail`` no puede producir ``OK``/``proceed``/
  ``DONE`` (lo garantiza la regla estructural de ``audit-result`` + el match
  exacto de evidencia). Evidencia incompleta o misbound falla cerrado.

Semántica de transiciones (sin combinaciones nuevas)
----------------------------------------------------

- ``OK``/``proceed``            -> ``DONE``
- ``PARCIAL``/``fix-and-retry`` -> ``CORRECTION_SENT``
- ``PARCIAL``/``escalate``      -> ``BLOCKED``
- ``BLOQ``/``escalate``         -> ``BLOCKED``

Estas combinaciones son las del ADR-0001 y ``state.apply_audit``; este puente no
añade ninguna nueva.
"""

import math
import re
from datetime import datetime
from typing import Any, Mapping

from .audit import canonical_digest, validate_audit_binding, validate_audit_result
from .contracts import ValidationError
from .human_notice import _parse_utc
from .review import validate_review_evidence_binding
from .state import TransitionError, apply_audit


class AuditReviewError(ValueError):
    """Fallo pre-efecto al ligar audit-result con review-evidence.

    Se lanza antes de ``apply_audit`` y sin efectos: no hay llamadas externas, ni
    escritura de estado, ni persistencia.
    """


# Combinaciones permitidas (espejo del ADR-0001 / ``audit._OUTCOMES``). Se
# mantiene aquí una copia explícita para que el puente valide la combinación
# inyectada sin acoplarse a un detalle privado de ``audit``; si ``audit`` las
# cambiara, ``validate_audit_result`` y ``apply_audit`` seguirían siendo la
# autoridad normativa y este chequeo sólo endurece (nunca amplía).
_OUTCOMES = frozenset({
    ("OK", "proceed"),
    ("PARCIAL", "fix-and-retry"),
    ("PARCIAL", "escalate"),
    ("BLOQ", "escalate"),
})

# Techo duro para la ventana de frescura de la auditoría (reviewed_at ->
# observed_at), en segundos.
_MAX_AUDIT_AGE_CEILING = 7200

_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def _require_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe usar minúsculas, dígitos o guiones")


def _require_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe ser sha256:<64 hex>")


def _validate_audit_age_policy(value: Any, exc: type) -> None:
    """Límites de la política de frescura de auditoría: finito, positivo, acotado."""
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)
            or not (0 < value <= _MAX_AUDIT_AGE_CEILING)):
        raise exc(
            f"max_audit_age_seconds debe ser finito positivo en "
            f"(0, {_MAX_AUDIT_AGE_CEILING:g}]"
        )


def _validate_audit_freshness(
    reviewed_at: Any, observed_at: Any,
    max_audit_age_seconds: Any, exc: type,
) -> None:
    """Política de frescura: observed >= reviewed y delta <= max.

    Todo se valida con la política EXTERNA; no se lee el reloj.
    """
    _validate_audit_age_policy(max_audit_age_seconds, exc)
    reviewed_dt = _parse_utc(reviewed_at, "reviewed_at", exc)
    observed_dt = _parse_utc(observed_at, "observed_at", exc)
    if observed_dt < reviewed_dt:
        raise exc("observed_at no puede preceder a reviewed_at")
    age = (observed_dt - reviewed_dt).total_seconds()
    if age > max_audit_age_seconds:
        raise exc("observed_at excede la edad máxima de auditoría")


def _derive_audit_evidence_from_review(review_evidence: Mapping[str, Any]) -> list:
    """Deriva la evidencia de auditoría esperada desde ``review-evidence``.

    Cada check produce una entrada ``evidence`` con el mismo ``evidence_id``,
    ``status`` y ``digest`` que en ``review-evidence``. La captura produce una
    entrada cerrada (``evidence_id == "capture"``, ``status == "pass"``) ligada
    al ``capture_digest``. El orden es el de los checks de review-evidence (que
    el validador de review-evidence exige ordenado por ``check_id``) seguido de
    la captura.
    """
    items = []
    for check in review_evidence["checks"]:
        items.append({
            "evidence_id": check["check_id"],
            "status": check["status"],
            "digest": check["digest"],
        })
    items.append({
        "evidence_id": "capture",
        "status": "pass",
        "digest": review_evidence["capture_digest"],
    })
    return items


def _evidence_signature(items: list) -> tuple:
    """Firma ordenada de una lista de evidencia para comparación exacta.

    Compara identidad (``evidence_id``), ``status`` y ``digest`` en orden. Así
    se rechazan checks omitidos, extra o reordenados, y captura omitida o con
    digest cambiado.
    """
    return tuple(
        (item["evidence_id"], item["status"], item["digest"]) for item in items
    )


def validate_audit_review_binding(
    audit_result: Mapping[str, Any],
    review_evidence: Mapping[str, Any],
    task_card: Mapping[str, Any],
    adapter: Mapping[str, Any],
    preflight_result: Mapping[str, Any],
    dispatch_receipt: Mapping[str, Any],
    human_notice: Mapping[str, Any],
    expected_run_id: str,
    expected_attempt_id: str,
    expected_session_name: str,
    expected_command: str,
    expected_max_preflight_age_seconds: float,
    message: str,
    expected_max_dispatch_age_seconds: float,
    expected_max_notice_age_seconds: float,
    expected_classification: str,
    expected_decision: str,
    expected_decision_reference: str,
    expected_observed_at: str,
    max_audit_age_seconds: float,
    expected_grant_id: str,
    expected_grant_digest: str,
) -> None:
    """Liga ``audit-result`` a ``review-evidence`` + cadena + decisión + autoridad.

    Reutiliza:

    - ``validate_review_evidence_binding``: cadena completa (tarjeta, adaptador,
      preflight, dispatch receipt, aviso, mensaje y políticas externas).
    - ``validate_audit_binding``: tarjeta, ``grant`` y ``run``/``attempt`` (H2).
    - ``validate_audit_result``: estructura del audit-result (incluida la
      bidireccionalidad ``capture`` <-> ``review_evidence_digest``).

    Exige además (propias del puente, sin duplicar reglas):

    - ``review_evidence_digest`` presente y coincidente con el review-evidence.
    - La evidencia del audit-result coincide **exactamente** (identidad/status/
      digest y orden) con la derivada desde review-evidence.
    - ``classification``, ``decision`` y ``authority_binding.decision_reference``
      coinciden con los parámetros externos inyectados (anti-auto-amplificación).
    - ``observed_at`` coincide **exactamente** con ``expected_observed_at`` y
      satisface la ventana ``max_audit_age_seconds`` externa respecto de
      ``review_evidence.reviewed_at`` (no se lee el reloj).
    - ``authority_binding.grant_id``/``grant_digest`` coinciden con
      ``expected_grant_id``/``expected_grant_digest`` externos, que a su vez
      deben coincidir con ``task_card.authority``: el grant de la tarjeta es
      correlación, no autoridad actual.

    La combinación ``classification``/``decision`` debe ser una de las permitidas
    por el ADR-0001; este chequeo sólo endurece, no amplía.
    """
    # 1. Estructura del audit-result (incluye bidireccionalidad capture <->
    #    review_evidence_digest y digest de review_evidence_digest si presente).
    validate_audit_result(audit_result)
    # 2. Cadena completa: review-evidence ligado a tarjeta/adapter/preflight/
    #    dispatch/aviso/mensaje/políticas. Reutiliza el validador existente.
    validate_review_evidence_binding(
        review_evidence, task_card, adapter, preflight_result,
        dispatch_receipt, human_notice,
        expected_run_id, expected_attempt_id,
        expected_session_name, expected_command,
        expected_max_preflight_age_seconds, message,
        expected_max_dispatch_age_seconds, expected_max_notice_age_seconds,
    )
    # 3. Binding H2: tarjeta, grant, run/attempt, task_card_digest y evidencia
    #    requerida (subconjunto). Reutiliza el validador existente.
    validate_audit_binding(
        audit_result, task_card, expected_run_id, expected_attempt_id,
    )
    # 4. review_evidence_digest: requerido para el puente y coincidente.
    if "review_evidence_digest" not in audit_result:
        raise ValidationError(
            "review_evidence_digest es requerido para ligar audit-result a review-evidence"
        )
    if audit_result["review_evidence_digest"] != canonical_digest(review_evidence):
        raise ValidationError(
            "review_evidence_digest no coincide con review-evidence"
        )
    # 5. Evidencia derivada exclusivamente desde review-evidence (match exacto).
    expected_evidence = _derive_audit_evidence_from_review(review_evidence)
    if (_evidence_signature(audit_result["evidence"])
            != _evidence_signature(expected_evidence)):
        raise ValidationError(
            "la evidencia de auditoría no coincide exactamente con la derivada "
            "desde review-evidence (identidad/status/digest u orden)"
        )
    # 6. Decisión inyectada: anti-auto-amplificación. El audit-result declara
    #    classification/decision/decision_reference y deben coincidir con la
    #    decisión externa del controlador/mantenedor.
    if audit_result["classification"] != expected_classification:
        raise ValidationError(
            "classification no coincide con la decisión esperada"
        )
    if audit_result["decision"] != expected_decision:
        raise ValidationError(
            "decision no coincide con la decisión esperada"
        )
    if audit_result["authority_binding"]["decision_reference"] != expected_decision_reference:
        raise ValidationError(
            "authority_binding.decision_reference no coincide con la decisión esperada"
        )
    # 7. Combinación permitida (endurece; validate_audit_result ya lo comprueba).
    outcome = (audit_result["classification"], audit_result["decision"])
    if outcome not in _OUTCOMES:
        raise ValidationError(
            "combinación classification/decision no permitida por el ADR-0001"
        )
    # 8. Política externa de auditoría: timestamp exacto + ventana de frescura.
    #    No se lee el reloj: expected_observed_at y max_audit_age_seconds son
    #    inyectados por el controlador. observed_at debe coincidir EXACTAMENTE
    #    con el esperado y satisfacer la ventana respecto de reviewed_at.
    _parse_utc(expected_observed_at, "expected_observed_at", ValidationError)
    if audit_result["observed_at"] != expected_observed_at:
        raise ValidationError(
            "observed_at no coincide con el timestamp esperado"
        )
    _validate_audit_freshness(
        review_evidence["reviewed_at"], audit_result["observed_at"],
        max_audit_age_seconds, ValidationError,
    )
    # 9. Autoridad externa inyectada: forma + coincidencia con tarjeta Y
    #    audit-result. El grant de la tarjeta es correlación, no autoridad
    #    actual: el controlador/mantenedor inyecta expected_grant_id/
    #    expected_grant_digest y el audit-result debe coincidir con ellos.
    _require_id(expected_grant_id, "expected_grant_id")
    _require_digest(expected_grant_digest, "expected_grant_digest")
    authority = task_card["authority"]
    if expected_grant_id != authority["grant_id"]:
        raise ValidationError(
            "expected_grant_id no coincide con la autoridad de la tarjeta"
        )
    if expected_grant_digest != canonical_digest(authority):
        raise ValidationError(
            "expected_grant_digest no coincide con la autoridad de la tarjeta"
        )
    binding = audit_result["authority_binding"]
    if binding["grant_id"] != expected_grant_id:
        raise ValidationError(
            "authority_binding.grant_id no coincide con la autoridad esperada"
        )
    if binding["grant_digest"] != expected_grant_digest:
        raise ValidationError(
            "authority_binding.grant_digest no coincide con la autoridad esperada"
        )


def apply_audit_from_review(
    audit_result: Mapping[str, Any],
    review_evidence: Mapping[str, Any],
    task_card: Mapping[str, Any],
    adapter: Mapping[str, Any],
    preflight_result: Mapping[str, Any],
    dispatch_receipt: Mapping[str, Any],
    human_notice: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_attempt_id: str,
    expected_session_name: str,
    expected_command: str,
    expected_max_preflight_age_seconds: float,
    message: str,
    expected_max_dispatch_age_seconds: float,
    expected_max_notice_age_seconds: float,
    expected_classification: str,
    expected_decision: str,
    expected_decision_reference: str,
    expected_observed_at: str,
    max_audit_age_seconds: float,
    expected_grant_id: str,
    expected_grant_digest: str,
    current_state: str,
):
    """Cierra la auditoría desde review-evidence; devuelve ``(audit_result, state)``.

    Exige ``current_state == REVIEWING`` y valida **todo** el binding antes de
    ``apply_audit``: no lanza procesos externos, no lee el reloj, no escribe
    estado ni archivos. Retorna el audit-result ligado junto con el estado
    derivado.

    Ningún valor autodeclarado amplía autoridad o frescura: la decisión
    (``classification``/``decision``/``decision_reference``) se valida contra
    parámetros externos; la autoridad (``grant_id``/``grant_digest``) se valida
    contra parámetros externos inyectados (no contra la sola tarjeta); el
    timestamp (``observed_at``) se valida contra ``expected_observed_at`` exacto
    y una ventana ``max_audit_age_seconds`` externa; la evidencia se deriva
    exclusivamente desde review-evidence; los digest y políticas se re_derivan
    desde la cadena.
    """
    # 1. Estado REVIEWING (pre-efecto; sin efectos).
    if current_state != "REVIEWING":
        raise AuditReviewError(
            "apply_audit_from_review exige estado REVIEWING"
        )
    # 2. Binding completo antes de apply_audit (sin efectos).
    try:
        validate_audit_review_binding(
            audit_result, review_evidence, task_card, adapter,
            preflight_result, dispatch_receipt, human_notice,
            expected_run_id, expected_attempt_id,
            expected_session_name, expected_command,
            expected_max_preflight_age_seconds, message,
            expected_max_dispatch_age_seconds, expected_max_notice_age_seconds,
            expected_classification, expected_decision, expected_decision_reference,
            expected_observed_at, max_audit_age_seconds,
            expected_grant_id, expected_grant_digest,
        )
    except ValidationError as error:
        raise AuditReviewError(
            "audit-result no liga con review-evidence, la decisión, el timestamp "
            "o la autoridad inyectada"
        ) from error
    # 3. Aplica la transición mediante la máquina de estados pura (H2).
    try:
        state = apply_audit(
            current_state, audit_result, task_card,
            expected_run_id, expected_attempt_id,
        )
    except TransitionError as error:
        raise AuditReviewError("transición de auditoría inválida") from error
    # 4. Retorna el audit-result ligado y el estado derivado.
    return audit_result, state
