"""Contratos locales para la supervision gobernada de agentes externos."""

from .adapter import validate_adapter_capabilities
from .audit import canonical_digest, validate_audit_binding, validate_audit_result
from .contracts import ValidationError, validate_task_card
from .host_observer import observe_opencode_tmux
from .host_runner import (
    HostObserverError,
    HostRunner,
    PaneObservation,
    ProductionHostRunner,
)
from .preflight import (
    PreflightError,
    PreflightResult,
    evaluate_preflight,
    validate_preflight_binding,
    validate_preflight_result,
)
from .state import TransitionError, apply_audit, transition

__all__ = [
    "HostObserverError", "HostRunner", "PaneObservation", "PreflightError",
    "PreflightResult", "ProductionHostRunner", "TransitionError",
    "ValidationError", "apply_audit", "canonical_digest", "evaluate_preflight",
    "observe_opencode_tmux", "transition", "validate_adapter_capabilities",
    "validate_audit_binding", "validate_audit_result",
    "validate_preflight_binding", "validate_preflight_result",
    "validate_task_card",
]
