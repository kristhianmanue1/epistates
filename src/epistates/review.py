"""Inspección post-ejecución ``opencode-tmux``: una captura y checks, una vez.

Separación de responsabilidades
-------------------------------

- ``host_runner`` observa (read-only), ``dispatch`` entrega (escritura) y este
  módulo **inspecciona** tras un aviso humano. Es la frontera que consume un
  aviso cerrado y produce ``review-evidence/v1``.

Fail-closed antes de cualquier efecto
-------------------------------------

- ``review_opencode_tmux`` valida primero la **cadena completa**: tarjeta,
  adaptador, preflight binding (outcome ok), dispatch receipt binding (preflight
  exacto, mensaje, política), human notice binding (recibo exacto, frescura).
  Si cualquier eslabón falla se lanza ``ReviewError`` **sin ninguna llamada** al
  runner.
- Exige ``current_state == WAITING_EXTERNAL``.
- Aplica frescura de aviso (notice) y de revisión (review) inyectadas.

Precálculo de transiciones antes de efectos
-------------------------------------------

- Antes de capturar o ejecutar checks se precalcula
  ``WAITING_EXTERNAL --notify--> REVIEW_READY --review--> REVIEWING``.
- Tras captura + checks sólo queda ensamblar el recibo con digest/longitud ya
  calculados (operación que no puede lanzar).

Una captura y cada check una sola vez; sin reintento
----------------------------------------------------

- Se llama ``capture_once`` exactamente una vez y ``run_check`` exactamente una
  vez por check requerido (orden determinista).
- Un fallo indeterminado (excepción del runner) produce
  ``IndeterminateReviewError`` y **no reintenta**: no hay segunda captura ni
  segundo intento de check.

Recibo sin contenido libre
--------------------------

- ``review-evidence/v1`` **no** guarda stdout/stderr ni el contenido de la
  captura: sólo digests, longitudes UTF-8, estados pass/fail y binding exacto.
- La clasificación ``OK``/``PARCIAL``/``BLOQ`` y ``apply_audit`` quedan **fuera**
  de este corte: el recibo aporta evidencia cruda; la decisión es otra autoridad.

Honestidad sobre unicidad global
--------------------------------

Esta función es **stateless**: no persiste ``event_id`` ni estado. Bloquea
replay sólo si el caller avanza el estado (``WAITING_EXTERNAL`` -> ``REVIEWING``)
fuera de la función. Un caller que vuelva a presentar el mismo aviso reclamando
``WAITING_EXTERNAL`` no puede detectarse aquí.
"""

import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from .adapter import validate_adapter_capabilities
from .audit import canonical_digest
from .contracts import ValidationError, validate_task_card
from .dispatch import validate_dispatch_receipt_binding
from .host_runner import HostObserverError, validate_session_name
from .human_notice import (
    _parse_utc,
    _validate_age_policy,
    _validate_freshness as _validate_notice_freshness,
    validate_human_notice_binding,
)
from .review_runner import (
    _CAPTURE_LINES_CEILING,
    _CAPTURE_LINES_FLOOR,
    CheckOutcome,
    CaptureOutcome,
    IndeterminateReviewError,
    ReviewRunner,
)
from .state import TransitionError, transition


class ReviewError(ValueError):
    """Fallo pre-efecto: nada se capturó ni ejecutó. Categoría pre-efecto."""


_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")

# Techo para la ventana de frescura de la revisión (notice -> review).
_MAX_NOTICE_AGE_CEILING = 7200

_PHASES = ("capture_once", "checks_once")

_REVIEW_EVIDENCE_FIELDS = frozenset({
    "schema", "task_id", "run_id", "attempt_id", "task_card_digest",
    "adapter_digest", "preflight_result_digest", "dispatch_receipt_digest",
    "human_notice_digest", "adapter_id", "session_name", "reviewed_at",
    "max_dispatch_age_seconds", "max_notice_age_seconds", "capture_digest",
    "capture_length_utf8", "capture_lines", "checks", "phases_confirmed",
    "final_state", "confirms",
})

_CHECK_STATUSES = frozenset({"pass", "fail"})


# ---------------------------------------------------------------------------
# Resolución de checks requeridos desde la tarjeta (catálogo confiable).
# ---------------------------------------------------------------------------


def _required_checks(task_card: Mapping[str, Any]) -> list:
    """Determina los check_ids requeridos desde la tarjeta.

    **Siempre** incluye todos los ``task_card.checks`` (además de los mapeos de
    ``evidence.required``). El caller nunca aporta argv: sólo identificadores.
    """
    required = set()
    # Todos los checks declarados siempre son requeridos.
    for check in task_card["checks"]:
        required.add(check["check_id"])
    evidence_map = {
        "worktree_status": "git_status",
        "diff_check": "diff_check",
    }
    for requirement in task_card["evidence"]["required"]:
        if requirement in evidence_map:
            required.add(evidence_map[requirement])
    return sorted(required)


# ---------------------------------------------------------------------------
# Validación estructural y binding de review-evidence/v1.
# ---------------------------------------------------------------------------


def _require_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe usar minúsculas, dígitos o guiones")


def _require_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe ser sha256:<64 hex>")


def _validate_notice_age_policy(value: Any, exc: type) -> None:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)
            or not (0 < value <= _MAX_NOTICE_AGE_CEILING)):
        raise exc(
            f"max_notice_age_seconds debe ser finito positivo en "
            f"(0, {_MAX_NOTICE_AGE_CEILING:g}]"
        )


def _validate_review_freshness(
    notified_at: Any, reviewed_at: Any,
    max_notice_age_seconds: Any, exc: type,
) -> None:
    _validate_notice_age_policy(max_notice_age_seconds, exc)
    notified_dt = _parse_utc(notified_at, "notified_at", exc)
    reviewed_dt = _parse_utc(reviewed_at, "reviewed_at", exc)
    if reviewed_dt < notified_dt:
        raise exc("reviewed_at no puede preceder a notified_at")
    age = (reviewed_dt - notified_dt).total_seconds()
    if age > max_notice_age_seconds:
        raise exc("reviewed_at excede la edad máxima del aviso")


def validate_review_evidence(evidence: Mapping[str, Any]) -> None:
    """Validación estructural de ``review-evidence/v1`` (sin refs externas)."""
    if not isinstance(evidence, Mapping):
        raise ValidationError("la evidencia debe ser un objeto JSON")
    missing = _REVIEW_EVIDENCE_FIELDS - evidence.keys()
    unknown = evidence.keys() - _REVIEW_EVIDENCE_FIELDS
    if missing:
        raise ValidationError(f"campos requeridos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise ValidationError(f"campos no permitidos: {rendered}")
    if evidence["schema"] != "epistates/review-evidence/v1":
        raise ValidationError("schema debe ser epistates/review-evidence/v1")
    for field in ("task_id", "run_id", "attempt_id", "adapter_id"):
        _require_id(evidence[field], field)
    for field in ("task_card_digest", "adapter_digest", "preflight_result_digest",
                  "dispatch_receipt_digest", "human_notice_digest", "capture_digest"):
        _require_digest(evidence[field], field)
    try:
        validate_session_name(evidence["session_name"])
    except HostObserverError as error:
        raise ValidationError("session_name debe ser un identificador cerrado") from error
    _parse_utc(evidence["reviewed_at"], "reviewed_at", ValidationError)
    _validate_age_policy(evidence["max_dispatch_age_seconds"], ValidationError)
    _validate_notice_age_policy(evidence["max_notice_age_seconds"], ValidationError)
    capture_length = evidence["capture_length_utf8"]
    if (not isinstance(capture_length, int) or isinstance(capture_length, bool)
            or capture_length < 0):
        raise ValidationError("capture_length_utf8 debe ser un entero no negativo")
    capture_lines = evidence["capture_lines"]
    if (not isinstance(capture_lines, int) or isinstance(capture_lines, bool)
            or not (_CAPTURE_LINES_FLOOR <= capture_lines <= _CAPTURE_LINES_CEILING)):
        raise ValidationError(
            f"capture_lines debe ser un entero en "
            f"[{_CAPTURE_LINES_FLOOR}, {_CAPTURE_LINES_CEILING}]"
        )
    checks = evidence["checks"]
    if not isinstance(checks, list) or not checks:
        raise ValidationError("checks debe ser una lista no vacía")
    seen = set()
    for item in checks:
        if not isinstance(item, Mapping) or set(item) != {
                "check_id", "status", "digest", "length_utf8"}:
            raise ValidationError(
                "cada check debe contener check_id, status, digest y length_utf8"
            )
        check_id = item["check_id"]
        if not isinstance(check_id, str) or check_id not in {
                "git_status", "diff_check", "unit_tests"}:
            raise ValidationError("check_id no está en el catálogo")
        if check_id in seen:
            raise ValidationError("check_id duplicado")
        seen.add(check_id)
        status = item["status"]
        if not isinstance(status, str) or status not in _CHECK_STATUSES:
            raise ValidationError("status de check debe ser pass o fail")
        _require_digest(item["digest"], "checks[].digest")
        length = item["length_utf8"]
        if (not isinstance(length, int) or isinstance(length, bool) or length < 0):
            raise ValidationError("length_utf8 debe ser un entero no negativo")
    if list(checks) != sorted(checks, key=lambda c: c["check_id"]):
        raise ValidationError("checks debe estar ordenado por check_id")
    phases = evidence["phases_confirmed"]
    if not isinstance(phases, list) or tuple(phases) != _PHASES:
        raise ValidationError("phases_confirmed debe ser [capture_once, checks_once]")
    if evidence["final_state"] != "REVIEWING":
        raise ValidationError("final_state debe ser REVIEWING")
    if evidence["confirms"] != "inspection_only":
        raise ValidationError("confirms debe ser inspection_only")


def validate_review_evidence_binding(
    evidence: Mapping[str, Any],
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
) -> None:
    """Liga evidencia a la cadena completa: tarjeta, adaptador, preflight,
    dispatch receipt, aviso y políticas externas.

    Re_deriva la frescura de aviso y de revisión con las políticas EXTERNAS del
    controlador (no las del recibo). Exige igualdad exacta de políticas para
    impedir auto-amplificación.
    """
    validate_review_evidence(evidence)
    validate_task_card(task_card)
    validate_adapter_capabilities(adapter)
    # Cadena completa: dispatch receipt binding (valida preflight ok + mensaje).
    validate_dispatch_receipt_binding(
        dispatch_receipt, task_card, adapter, preflight_result,
        expected_run_id, expected_attempt_id,
        expected_session_name, expected_command,
        expected_max_preflight_age_seconds, message,
    )
    # Aviso ligado al recibo exacto.
    validate_human_notice_binding(
        human_notice, task_card, adapter, dispatch_receipt,
        expected_run_id, expected_attempt_id, expected_session_name,
        expected_max_dispatch_age_seconds,
    )
    # Políticas externas: límites + igualdad exacta con el recibo.
    _validate_age_policy(expected_max_dispatch_age_seconds, ValidationError)
    _validate_notice_age_policy(expected_max_notice_age_seconds, ValidationError)
    if evidence["max_dispatch_age_seconds"] != expected_max_dispatch_age_seconds:
        raise ValidationError(
            "max_dispatch_age_seconds no coincide con la política esperada"
        )
    if evidence["max_notice_age_seconds"] != expected_max_notice_age_seconds:
        raise ValidationError(
            "max_notice_age_seconds no coincide con la política esperada"
        )
    # Binding de identidad.
    if evidence["task_id"] != task_card["task_id"]:
        raise ValidationError("task_id no coincide con la tarjeta")
    if evidence["run_id"] != expected_run_id:
        raise ValidationError("run_id no coincide con el contexto esperado")
    if evidence["attempt_id"] != expected_attempt_id:
        raise ValidationError("attempt_id no coincide con el contexto esperado")
    if evidence["adapter_id"] != adapter["adapter_id"]:
        raise ValidationError("adapter_id no coincide con el adaptador")
    if evidence["session_name"] != expected_session_name:
        raise ValidationError("session_name no coincide con el esperado")
    # Binding de checks: igualdad EXACTA con los requeridos por la tarjeta.
    required = _required_checks(task_card)
    observed = [item["check_id"] for item in evidence["checks"]]
    if observed != required:
        raise ValidationError(
            "checks no coinciden exactamente con los requeridos por la tarjeta"
        )
    # Binding de digests (cadena explícita).
    if evidence["task_card_digest"] != canonical_digest(task_card):
        raise ValidationError("task_card_digest no coincide con la tarjeta")
    if evidence["adapter_digest"] != canonical_digest(adapter):
        raise ValidationError("adapter_digest no coincide con el adaptador")
    if evidence["preflight_result_digest"] != canonical_digest(preflight_result):
        raise ValidationError("preflight_result_digest no coincide con el preflight")
    if evidence["dispatch_receipt_digest"] != canonical_digest(dispatch_receipt):
        raise ValidationError("dispatch_receipt_digest no coincide con el recibo")
    if evidence["human_notice_digest"] != canonical_digest(human_notice):
        raise ValidationError("human_notice_digest no coincide con el aviso")
    # Re_deriva frescura de aviso con política externa.
    _validate_notice_freshness(
        dispatch_receipt["dispatched_at"], human_notice["notified_at"],
        expected_max_dispatch_age_seconds, ValidationError,
    )
    # Re_deriva frescura de revisión con política externa.
    _validate_review_freshness(
        human_notice["notified_at"], evidence["reviewed_at"],
        expected_max_notice_age_seconds, ValidationError,
    )


# ---------------------------------------------------------------------------
# Orquestación: una captura + checks una vez, fail-closed, sin reintento.
# ---------------------------------------------------------------------------


def review_opencode_tmux(
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
    reviewed_at: str,
    current_state: str,
    runner: ReviewRunner,
):
    """Inspección fail-closed tras aviso; devuelve ``(evidence, final_state)``.

    Requiere la cadena completa validada, estado ``WAITING_EXTERNAL`` y políticas
    de frescura inyectadas. Precalcula transiciones antes de efectos; ejecuta una
    captura y cada check requerido exactamente una vez; no reintenta ante resultado
    indeterminado. La evidencia no guarda stdout/stderr/captura.
    """
    # 1. Validación de la cadena completa antes de cualquier efecto.
    try:
        validate_dispatch_receipt_binding(
            dispatch_receipt, task_card, adapter, preflight_result,
            expected_run_id, expected_attempt_id,
            expected_session_name, expected_command,
            expected_max_preflight_age_seconds, message,
        )
    except ValidationError as error:
        raise ReviewError("dispatch receipt binding inválido") from error
    try:
        validate_human_notice_binding(
            human_notice, task_card, adapter, dispatch_receipt,
            expected_run_id, expected_attempt_id, expected_session_name,
            expected_max_dispatch_age_seconds,
        )
    except ValidationError as error:
        raise ReviewError("human notice binding inválido") from error
    # 2. Estado WAITING_EXTERNAL (exigido por el evento notify).
    if current_state != "WAITING_EXTERNAL":
        raise ReviewError("review exige estado WAITING_EXTERNAL")
    # 3. Validaciones pre-efecto: sesión, timestamps, políticas, runner.
    session = _coerce_session(expected_session_name)
    _parse_utc(reviewed_at, "reviewed_at", ReviewError)
    _validate_age_policy(expected_max_dispatch_age_seconds, ReviewError)
    _validate_notice_age_policy(expected_max_notice_age_seconds, ReviewError)
    if runner is None:
        raise ReviewError("runner es requerido")
    # Frescura de revisión (reviewed_at vs notified_at).
    _validate_review_freshness(
        human_notice["notified_at"], reviewed_at,
        expected_max_notice_age_seconds, ReviewError,
    )
    # 4. Precálculo de transiciones antes del primer efecto.
    try:
        after_notify = transition(current_state, "notify")
        final_state = transition(after_notify, "review")
    except TransitionError as error:
        raise ReviewError("transición de estado inválida") from error
    if final_state != "REVIEWING":
        raise ReviewError("transición de estado inesperada")
    # 5. Checks requeridos (catálogo, orden determinista).
    required = _required_checks(task_card)
    if not required:
        raise ReviewError("la tarjeta no declara checks requeridos")
    # Digests pre-efecto (no pueden lanzar tras validación previa).
    task_card_digest = canonical_digest(task_card)
    adapter_digest = canonical_digest(adapter)
    preflight_result_digest = canonical_digest(preflight_result)
    dispatch_receipt_digest = canonical_digest(dispatch_receipt)
    human_notice_digest = canonical_digest(human_notice)
    # 6. Una captura, exactamente una vez.
    try:
        capture = runner.capture_once(session)
    except Exception as error:
        raise IndeterminateReviewError(
            "captura intentada: resultado indeterminado; NO reintentar"
        ) from error
    _validate_capture_outcome(capture)
    # 7. Cada check requerido, exactamente una vez, orden determinista.
    outcomes = []
    for check_id in required:
        try:
            outcome = runner.run_check(check_id)
        except Exception as error:
            raise IndeterminateReviewError(
                f"check {check_id} intentado: resultado indeterminado; NO reintentar"
            ) from error
        _validate_check_outcome(outcome, check_id)
        outcomes.append(outcome)
    # 8. Ensamblado del recibo: sólo digest/longitud ya calculados. Sin captura.
    evidence = {
        "schema": "epistates/review-evidence/v1",
        "task_id": task_card["task_id"],
        "run_id": expected_run_id,
        "attempt_id": expected_attempt_id,
        "task_card_digest": task_card_digest,
        "adapter_digest": adapter_digest,
        "preflight_result_digest": preflight_result_digest,
        "dispatch_receipt_digest": dispatch_receipt_digest,
        "human_notice_digest": human_notice_digest,
        "adapter_id": adapter["adapter_id"],
        "session_name": session,
        "reviewed_at": reviewed_at,
        "max_dispatch_age_seconds": expected_max_dispatch_age_seconds,
        "max_notice_age_seconds": expected_max_notice_age_seconds,
        "capture_digest": capture.digest,
        "capture_length_utf8": capture.length_utf8,
        "capture_lines": capture.capture_lines,
        "checks": [
            {
                "check_id": o.check_id,
                "status": o.status,
                "digest": o.digest,
                "length_utf8": o.length_utf8,
            }
            for o in outcomes
        ],
        "phases_confirmed": list(_PHASES),
        "final_state": final_state,
        "confirms": "inspection_only",
    }
    # 9. Validación estructural del documento ensamblado (defensa, sin efectos).
    try:
        validate_review_evidence(evidence)
    except ValidationError as error:
        raise IndeterminateReviewError(
            "evidencia ensamblada inválida; NO reintentar"
        ) from error
    return evidence, final_state


def _coerce_session(value: Any) -> str:
    try:
        return validate_session_name(value)
    except HostObserverError as error:
        raise ReviewError("session_name debe ser un identificador cerrado") from error


# ---------------------------------------------------------------------------
# Validación de resultados del runner tras un efecto (defensa contra fakes).
# ---------------------------------------------------------------------------


def _require_int(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise IndeterminateReviewError(f"{name} debe ser un entero")


def _validate_capture_outcome(capture: Any) -> None:
    """Valida completamente un CaptureOutcome tras el efecto.

    No confía en el tipo NamedTuple: comprueba digest, longitud y capture_lines.
    Un resultado inválido es indeterminado (sin reintento).
    """
    if not isinstance(capture, CaptureOutcome):
        raise IndeterminateReviewError("capture_once no devolvió CaptureOutcome")
    if not isinstance(capture.digest, str) or not _DIGEST_PATTERN.fullmatch(capture.digest):
        raise IndeterminateReviewError("capture_once con digest inválido")
    _require_int(capture.length_utf8, "capture_length_utf8")
    if capture.length_utf8 < 0:
        raise IndeterminateReviewError("capture_length_utf8 no puede ser negativo")
    _require_int(capture.capture_lines, "capture_lines")
    if not (_CAPTURE_LINES_FLOOR <= capture.capture_lines <= _CAPTURE_LINES_CEILING):
        raise IndeterminateReviewError("capture_lines fuera de rango")


def _validate_check_outcome(outcome: Any, expected_check_id: str) -> None:
    """Valida completamente un CheckOutcome tras el efecto.

    No confía en el tipo NamedTuple: comprueba check_id, status, digest y
    longitud. Un resultado inválido es indeterminado (sin reintento).
    """
    if not isinstance(outcome, CheckOutcome):
        raise IndeterminateReviewError(
            f"run_check no devolvió CheckOutcome para {expected_check_id}"
        )
    if outcome.check_id != expected_check_id:
        raise IndeterminateReviewError(
            f"check_id del resultado ({outcome.check_id}) != esperado ({expected_check_id})"
        )
    if outcome.status not in _CHECK_STATUSES:
        raise IndeterminateReviewError(f"status inválido para {expected_check_id}")
    if not isinstance(outcome.digest, str) or not _DIGEST_PATTERN.fullmatch(outcome.digest):
        raise IndeterminateReviewError(f"digest inválido para {expected_check_id}")
    _require_int(outcome.length_utf8, f"length_utf8 de {expected_check_id}")
    if outcome.length_utf8 < 0:
        raise IndeterminateReviewError(f"length_utf8 negativo para {expected_check_id}")
