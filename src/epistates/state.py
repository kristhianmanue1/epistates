"""Máquina de estados cerrada y sin persistencia para una ejecución."""

from typing import Any, Mapping

from .audit import _state_after_audit


class TransitionError(ValueError):
    """Una transición no pertenece al protocolo o carece de auditoría válida."""


_TERMINAL = {"DONE", "BLOCKED"}
_OPERATIONAL = {
    ("PREPARED", "dispatch"): "DISPATCHED",
    ("DISPATCHED", "wait"): "WAITING_EXTERNAL",
    ("WAITING_EXTERNAL", "notify"): "REVIEW_READY",
    ("REVIEW_READY", "review"): "REVIEWING",
    ("CORRECTION_SENT", "wait"): "WAITING_EXTERNAL",
}
_ACTIVE = {
    "PREPARED", "DISPATCHED", "WAITING_EXTERNAL", "REVIEW_READY", "REVIEWING",
    "CORRECTION_SENT",
}
_BLOCKABLE = _ACTIVE - {"REVIEWING"}


def transition(current: str, event: str) -> str:
    """Aplica un evento operativo conocido; nunca procesa resultados de auditoría."""
    if not isinstance(current, str) or not isinstance(event, str):
        raise TransitionError("estado o evento desconocido")
    if current in _TERMINAL:
        raise TransitionError(f"{current} es terminal")
    if current not in _ACTIVE:
        raise TransitionError("estado o evento desconocido")
    if event == "block" and current in _BLOCKABLE:
        return "BLOCKED"
    try:
        return _OPERATIONAL[(current, event)]
    except KeyError as exc:
        raise TransitionError(f"transición no permitida: {current} + {event}") from exc


def apply_audit(
    current: str, result: Mapping[str, Any], task_card: Mapping[str, Any],
    expected_run_id: str, expected_attempt_id: str,
) -> str:
    """Finaliza REVIEWING sólo mediante un resultado auditado y coherente."""
    if current != "REVIEWING":
        raise TransitionError("una auditoría sólo puede aplicarse desde REVIEWING")
    try:
        return _state_after_audit(result, task_card, expected_run_id, expected_attempt_id)
    except ValueError as exc:
        raise TransitionError(f"resultado de auditoría inválido: {exc}") from exc
