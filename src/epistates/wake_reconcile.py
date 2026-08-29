"""Reconciliación terminal E4 read-only sobre observadores inyectados."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from .delivery_ledger import DeliveryAttempt, DeliveryLedgerStore


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_OUTCOMES = frozenset({"pending", "completed", "failed", "ambiguous"})
_TERMINAL_STATES = frozenset({"completed", "failed", "ambiguous"})


@dataclass(frozen=True)
class TerminalObservation:
    """Resumen saneado; nunca contiene texto, prompt, error libre o secreto."""

    target_id: str
    body_digest: str
    outcome: str
    terminal: bool
    has_nonempty_text: bool
    has_tool_parts: bool
    evidence_digest: str


class TerminalObserver(Protocol):
    """Puerto de lectura; no expone operación de envío."""

    def delivery_binding(self, nonce: str) -> Mapping[str, str]:
        ...

    def observe(self, target_id: str, nonce: str) -> TerminalObservation:
        ...


def _internal_evidence(nonce: str, result_class: str) -> str:
    raw = json.dumps({"nonce": nonce, "result_class": result_class},
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class WakeTerminalReconciler:
    """Usa el ledger como verdad y sólo aplica transiciones monotónicas."""

    def __init__(self, ledger: DeliveryLedgerStore, observer: TerminalObserver):
        self.ledger = ledger
        self.observer = observer
        self._disabled = (
            not isinstance(ledger, DeliveryLedgerStore) or ledger._disabled or
            not callable(getattr(observer, "delivery_binding", None)) or
            not callable(getattr(observer, "observe", None))
        )

    @staticmethod
    def _expected_binding(attempt: DeliveryAttempt) -> dict:
        return {
            "provider_id": attempt.provider_id,
            "provider_version": attempt.provider_version,
            "agent_id": attempt.agent_id,
            "model_id": attempt.model_id,
            "body_digest": attempt.body_digest,
        }

    def _binding_matches(self, attempt: DeliveryAttempt) -> bool:
        try:
            binding = self.observer.delivery_binding(attempt.nonce)
            observed = dict(binding) if isinstance(binding, Mapping) else None
        except Exception:
            return False
        return observed == self._expected_binding(attempt)

    def _transition(self, attempt: DeliveryAttempt, *, state: str,
                    observed_at: str, result_class: str,
                    evidence_digest: str = "") -> str:
        evidence = evidence_digest or _internal_evidence(
            attempt.nonce, result_class)
        outcome = self.ledger.transition(
            nonce=attempt.nonce, expected_state=attempt.state,
            new_state=state, observed_at=observed_at,
            result_class=result_class, evidence_digest=evidence,
        )
        if outcome == "updated":
            return state
        return outcome

    @staticmethod
    def _valid_observation(value: object) -> bool:
        return (
            isinstance(value, TerminalObservation) and
            isinstance(value.target_id, str) and
            isinstance(value.body_digest, str) and
            _DIGEST.fullmatch(value.body_digest) is not None and
            isinstance(value.outcome, str) and value.outcome in _OUTCOMES and
            isinstance(value.terminal, bool) and
            isinstance(value.has_nonempty_text, bool) and
            isinstance(value.has_tool_parts, bool) and
            isinstance(value.evidence_digest, str) and
            _DIGEST.fullmatch(value.evidence_digest) is not None
        )

    def reconcile(self, *, nonce: str, observed_at: str) -> str:
        """Observa una vez como máximo; nunca envía ni reintenta."""
        if self._disabled:
            return "disabled"
        attempt = self.ledger.get(nonce)
        if attempt is None:
            return "disabled" if self.ledger._disabled else "not_found"
        if attempt.state in _TERMINAL_STATES:
            return attempt.state
        if attempt.state == "reserved":
            return "conflict"
        if attempt.state == "submitting":
            # Sin request id público ligado no puede demostrarse si hubo I/O.
            return self._transition(
                attempt, state="ambiguous", observed_at=observed_at,
                result_class="reconcile-submitting-no-binding",
            )
        if attempt.state != "submitted":
            return "conflict"
        if not self._binding_matches(attempt):
            return "mismatch"
        try:
            observation: object = self.observer.observe(
                attempt.target_id, attempt.nonce)
        except Exception:
            observation = None
        if not self._valid_observation(observation):
            return self._transition(
                attempt, state="ambiguous", observed_at=observed_at,
                result_class="provider-observation-invalid",
            )
        assert isinstance(observation, TerminalObservation)
        if (observation.target_id != attempt.target_id or
                observation.body_digest != attempt.body_digest):
            return self._transition(
                attempt, state="ambiguous", observed_at=observed_at,
                result_class="provider-binding-mismatch",
            )
        if observation.has_tool_parts:
            return self._transition(
                attempt, state="failed", observed_at=observed_at,
                result_class="provider-tool-part",
                evidence_digest=observation.evidence_digest,
            )
        if observation.outcome == "pending" and not observation.terminal:
            return "pending"
        if (observation.outcome == "completed" and observation.terminal and
                observation.has_nonempty_text):
            return self._transition(
                attempt, state="completed", observed_at=observed_at,
                result_class="provider-terminal-completed",
                evidence_digest=observation.evidence_digest,
            )
        if observation.outcome == "failed" and observation.terminal:
            return self._transition(
                attempt, state="failed", observed_at=observed_at,
                result_class="provider-terminal-failed",
                evidence_digest=observation.evidence_digest,
            )
        result_class = (
            "provider-terminal-empty" if observation.terminal and
            not observation.has_nonempty_text
            else "provider-observation-ambiguous"
        )
        return self._transition(
            attempt, state="ambiguous", observed_at=observed_at,
            result_class=result_class,
            evidence_digest=observation.evidence_digest,
        )


__all__ = ["TerminalObservation", "TerminalObserver", "WakeTerminalReconciler"]
