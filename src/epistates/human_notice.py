"""Aviso humano cerrado ``epistates/human-notice/v1``: sólo identidad y evento.

El aviso es una señal humana de finalización. Contiene EXCLUSIVAMENTE identidad
(``task``/``run``/``attempt``/``adapter``/``session``) y un evento catalogado.
No transporta prompt, comando, autoridad ni texto libre. Sólo habilita
inspección: no concede permiso de escritura ni autoriza aceptación.

El aviso se liga al ``dispatch_receipt`` EXACTO mediante digest. La frescura
inyectada (``notified_at`` vs ``dispatched_at``) y la política externa limitan
la ventana y previenen replay de un aviso antiguo. El binding es fail-closed:
una mala ligadura, estado incorrecto o frescura violada producen cero llamadas
al runner de inspección.

Honestidad sobre unicidad global
--------------------------------

Esta validación es **stateless**: no persiste ``event_id`` ni estado. Bloquea
replay sólo si el caller avanza el estado fuera de la función (de
``WAITING_EXTERNAL`` a ``REVIEWING``). Un caller que vuelva a presentar el mismo
aviso reclamando ``WAITING_EXTERNAL`` no puede detectarse aquí: la unicidad
global exige persistir ``(run_id, attempt_id, event_id, estado)`` fuera.
"""

import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from .adapter import validate_adapter_capabilities
from .audit import canonical_digest
from .contracts import ValidationError, validate_task_card
from .dispatch import validate_dispatch_receipt
from .host_runner import HostObserverError, validate_session_name


class HumanNoticeError(ValueError):
    """El aviso humano no satisface su contrato o su ligadura."""


# Catálogo cerrado de eventos. Un aviso sólo declara un evento de este conjunto;
# nunca texto libre, comando ni autoridad.
_EVENT_CATALOG = frozenset({"external_completion"})

_HUMAN_NOTICE_FIELDS = frozenset({
    "schema", "task_id", "run_id", "attempt_id", "task_card_digest",
    "adapter_digest", "dispatch_receipt_digest", "adapter_id",
    "session_name", "event_id", "notified_at", "max_dispatch_age_seconds",
})

_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_UTC_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z"
)

# Techo duro para la ventana de frescura del aviso (segundos).
_MAX_DISPATCH_AGE_CEILING = 7200


def _require_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe usar minúsculas, dígitos o guiones")


def _require_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe ser sha256:<64 hex>")


def _parse_utc(value: Any, field: str, exc: type) -> datetime:
    if not isinstance(value, str) or not _UTC_PATTERN.fullmatch(value):
        raise exc(f"{field} debe ser RFC3339 UTC terminado en Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise exc(f"{field} debe ser RFC3339 UTC válido") from error
    if parsed.tzinfo != timezone.utc:
        raise exc(f"{field} debe estar en UTC")
    return parsed


def _validate_age_policy(value: Any, exc: type) -> None:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)
            or not (0 < value <= _MAX_DISPATCH_AGE_CEILING)):
        raise exc(
            f"max_dispatch_age_seconds debe ser finito positivo en "
            f"(0, {_MAX_DISPATCH_AGE_CEILING:g}]"
        )


def _validate_freshness(
    dispatched_at: Any, notified_at: Any,
    max_dispatch_age_seconds: Any, exc: type,
) -> None:
    """Política de frescura: notified >= dispatched y age <= max.

    Todo se valida antes de cualquier efecto.
    """
    _validate_age_policy(max_dispatch_age_seconds, exc)
    dispatched_dt = _parse_utc(dispatched_at, "dispatched_at", exc)
    notified_dt = _parse_utc(notified_at, "notified_at", exc)
    if notified_dt < dispatched_dt:
        raise exc("notified_at no puede preceder a dispatched_at")
    age = (notified_dt - dispatched_dt).total_seconds()
    if age > max_dispatch_age_seconds:
        raise exc("notified_at excede la edad máxima del dispatch")


def validate_human_notice(notice: Mapping[str, Any]) -> None:
    """Validación estructural de ``human-notice/v1`` (sin refs externas)."""
    if not isinstance(notice, Mapping):
        raise ValidationError("el aviso debe ser un objeto JSON")
    missing = _HUMAN_NOTICE_FIELDS - notice.keys()
    unknown = notice.keys() - _HUMAN_NOTICE_FIELDS
    if missing:
        raise ValidationError(f"campos requeridos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise ValidationError(f"campos no permitidos: {rendered}")
    if notice["schema"] != "epistates/human-notice/v1":
        raise ValidationError("schema debe ser epistates/human-notice/v1")
    for field in ("task_id", "run_id", "attempt_id", "adapter_id"):
        _require_id(notice[field], field)
    _require_digest(notice["task_card_digest"], "task_card_digest")
    _require_digest(notice["adapter_digest"], "adapter_digest")
    _require_digest(notice["dispatch_receipt_digest"], "dispatch_receipt_digest")
    try:
        validate_session_name(notice["session_name"])
    except HostObserverError as error:
        raise ValidationError("session_name debe ser un identificador cerrado") from error
    event_id = notice["event_id"]
    if not isinstance(event_id, str) or event_id not in _EVENT_CATALOG:
        raise ValidationError("event_id no está en el catálogo de eventos")
    _parse_utc(notice["notified_at"], "notified_at", ValidationError)
    _validate_age_policy(notice["max_dispatch_age_seconds"], ValidationError)


def validate_human_notice_binding(
    notice: Mapping[str, Any],
    task_card: Mapping[str, Any],
    adapter: Mapping[str, Any],
    dispatch_receipt: Mapping[str, Any],
    expected_run_id: str,
    expected_attempt_id: str,
    expected_session_name: str,
    expected_max_dispatch_age_seconds: float,
) -> None:
    """Liga aviso, tarjeta, adaptador y ``dispatch_receipt`` exacto.

    La política de frescura es **externa** (``expected_max_dispatch_age_seconds``):
    se valida con los mismos límites, se exige **igualdad exacta** con el aviso
    (para impedir auto-amplificación) y se re_deriva la frescura con la política
    externa. Nunca se confía sólo en el aviso.

    No valida la cadena completa del ``dispatch_receipt`` (preflight + mensaje):
    eso es responsabilidad del binding del recibo. Aquí sólo se liga el aviso al
    recibo estructuralmente y por digest.
    """
    validate_human_notice(notice)
    validate_task_card(task_card)
    validate_adapter_capabilities(adapter)
    validate_dispatch_receipt(dispatch_receipt)
    _require_id(expected_run_id, "expected_run_id")
    _require_id(expected_attempt_id, "expected_attempt_id")
    try:
        validate_session_name(expected_session_name)
    except HostObserverError as error:
        raise ValidationError(
            "expected_session_name debe ser un identificador cerrado"
        ) from error
    _validate_age_policy(expected_max_dispatch_age_seconds, ValidationError)
    # Política externa: igualdad exacta con el aviso (impide auto-amplificación).
    if notice["max_dispatch_age_seconds"] != expected_max_dispatch_age_seconds:
        raise ValidationError(
            "max_dispatch_age_seconds no coincide con la política esperada"
        )
    # Binding de identidad entre aviso, tarjeta, adaptador y recibo.
    if notice["task_id"] != task_card["task_id"]:
        raise ValidationError("task_id no coincide con la tarjeta")
    if notice["run_id"] != expected_run_id:
        raise ValidationError("run_id no coincide con el contexto esperado")
    if notice["attempt_id"] != expected_attempt_id:
        raise ValidationError("attempt_id no coincide con el contexto esperado")
    if notice["adapter_id"] != adapter["adapter_id"]:
        raise ValidationError("adapter_id no coincide con el adaptador")
    if notice["session_name"] != expected_session_name:
        raise ValidationError("session_name no coincide con el esperado")
    if dispatch_receipt["task_id"] != task_card["task_id"]:
        raise ValidationError("dispatch_receipt task_id no coincide con la tarjeta")
    if dispatch_receipt["run_id"] != expected_run_id:
        raise ValidationError("dispatch_receipt run_id no coincide")
    if dispatch_receipt["attempt_id"] != expected_attempt_id:
        raise ValidationError("dispatch_receipt attempt_id no coincide")
    if dispatch_receipt["session_name"] != expected_session_name:
        raise ValidationError("dispatch_receipt session_name no coincide")
    # Binding de digests: aviso ligado al recibo EXACTO.
    if notice["task_card_digest"] != canonical_digest(task_card):
        raise ValidationError("task_card_digest no coincide con la tarjeta")
    if notice["adapter_digest"] != canonical_digest(adapter):
        raise ValidationError("adapter_digest no coincide con el adaptador")
    if notice["dispatch_receipt_digest"] != canonical_digest(dispatch_receipt):
        raise ValidationError("dispatch_receipt_digest no coincide con el recibo")
    # Re_deriva la frescura con la política EXTERNA, no la del aviso.
    _validate_freshness(
        dispatch_receipt["dispatched_at"], notice["notified_at"],
        expected_max_dispatch_age_seconds, ValidationError,
    )
