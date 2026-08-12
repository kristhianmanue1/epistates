"""Contratos locales para la supervision gobernada de agentes externos."""

from .adapter import validate_adapter_capabilities
from .audit import canonical_digest, validate_audit_binding, validate_audit_result
from .contracts import ValidationError, validate_task_card
from .dispatch import (
    DispatchError,
    IndeterminateDispatchError,
    LiteralDispatcher,
    PartialDispatchError,
    TmuxLiteralDispatcher,
    dispatch_literal_opencode_tmux,
    validate_dispatch_receipt,
    validate_dispatch_receipt_binding,
)
from .host_observer import observe_opencode_tmux
from .host_runner import (
    HostObserverError,
    HostRunner,
    PaneObservation,
    ProductionHostRunner,
)
from .human_notice import (
    HumanNoticeError,
    validate_human_notice,
    validate_human_notice_binding,
)
from .preflight import (
    PreflightError,
    PreflightResult,
    evaluate_preflight,
    validate_preflight_binding,
    validate_preflight_result,
)
from .review import (
    IndeterminateReviewError,
    ReviewError,
    review_opencode_tmux,
    validate_review_evidence,
    validate_review_evidence_binding,
)
from .review_runner import (
    CaptureOutcome,
    CheckOutcome,
    ReviewRunner,
    ReviewRunnerError,
    TmuxReviewRunner,
)
from .state import TransitionError, apply_audit, transition

__all__ = [
    "CaptureOutcome", "CheckOutcome", "DispatchError", "HostObserverError",
    "HostRunner", "HumanNoticeError", "IndeterminateDispatchError",
    "IndeterminateReviewError", "LiteralDispatcher", "PaneObservation",
    "PartialDispatchError", "PreflightError", "PreflightResult",
    "ProductionHostRunner", "ReviewError", "ReviewRunner",
    "ReviewRunnerError", "TmuxLiteralDispatcher", "TmuxReviewRunner",
    "TransitionError", "ValidationError", "apply_audit", "canonical_digest",
    "dispatch_literal_opencode_tmux", "evaluate_preflight",
    "observe_opencode_tmux", "review_opencode_tmux", "transition",
    "validate_adapter_capabilities", "validate_audit_binding",
    "validate_audit_result", "validate_dispatch_receipt",
    "validate_dispatch_receipt_binding", "validate_human_notice",
    "validate_human_notice_binding", "validate_preflight_binding",
    "validate_preflight_result", "validate_review_evidence",
    "validate_review_evidence_binding", "validate_task_card",
]
