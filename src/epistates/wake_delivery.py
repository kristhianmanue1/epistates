"""Reserva y submission durable E4 con puerto inyectado."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Mapping, Protocol

from .delivery_ledger import DeliveryLedgerStore
from .wake_guard import WakeGuardStore


class WakeDeliveryCoordinator:
    """Une dos stores internos sólo cuando comparten la misma base SQLite."""

    def __init__(self, guard: WakeGuardStore, ledger: DeliveryLedgerStore):
        self.guard = guard
        self.ledger = ledger
        try:
            same_path = Path(guard.path).resolve() == Path(ledger.path).resolve()
        except (AttributeError, OSError, TypeError, ValueError):
            same_path = False
        self._disabled = (
            not isinstance(guard, WakeGuardStore) or
            not isinstance(ledger, DeliveryLedgerStore) or
            not same_path or guard._disabled or ledger._disabled
        )

    def reserve(self, *, receipt_digest: str, target_id: str, nonce: str,
                dispatched_at: str, observed_at: str, ttl_seconds: int,
                provider_id: str, provider_version: str, agent_id: str,
                model_id: str, body_digest: str) -> str:
        """Reserva cuota e intento delivery en una transacción, sin más efectos."""
        if self._disabled or self.guard._disabled or self.ledger._disabled:
            return "disabled"
        guard_values = self.guard._prepare_reservation(
            receipt_digest=receipt_digest, target_id=target_id, nonce=nonce,
            dispatched_at=dispatched_at, observed_at=observed_at,
            ttl_seconds=ttl_seconds,
        )
        if isinstance(guard_values, str):
            return guard_values
        delivery_values = self.ledger._prepare_reserved(
            nonce=nonce, receipt_digest=receipt_digest, target_id=target_id,
            provider_id=provider_id, provider_version=provider_version,
            agent_id=agent_id, model_id=model_id, body_digest=body_digest,
            observed_at=observed_at,
        )
        if isinstance(delivery_values, str):
            return delivery_values
        try:
            with self.guard._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                guard_result = self.guard._reserve_in_transaction(
                    db, receipt_digest=receipt_digest, target_id=target_id,
                    nonce=nonce, observed_at=observed_at, now=guard_values,
                )
                if guard_result != "reserved":
                    db.rollback()
                    return guard_result
                delivery_result = self.ledger._create_reserved_in_transaction(
                    db, delivery_values, idempotent_replay=False,
                )
                if delivery_result != "reserved":
                    db.rollback()
                    return delivery_result
        except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
            self._disabled = True
            self.guard._disabled = True
            self.ledger._disabled = True
            return "disabled"
        return "reserved"


class WakePort(Protocol):
    """Superficie mínima inyectable; no proporciona transporte por sí misma."""

    def delivery_binding(self, nonce: str) -> Mapping[str, str]:
        ...

    def request_wake(self, session_id: str, nonce: str) -> str:
        ...


def _evidence_digest(nonce: str, result_class: str) -> str:
    raw = json.dumps({"nonce": nonce, "result_class": result_class},
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class WakeSubmissionCoordinator:
    """Realiza como máximo una llamada inyectada para un intento reservado."""

    def __init__(self, guard: WakeGuardStore, ledger: DeliveryLedgerStore,
                 port: WakePort):
        self.guard = guard
        self.ledger = ledger
        self.port = port
        try:
            same_path = Path(guard.path).resolve() == Path(ledger.path).resolve()
        except (AttributeError, OSError, TypeError, ValueError):
            same_path = False
        self._disabled = (
            not isinstance(guard, WakeGuardStore) or
            not isinstance(ledger, DeliveryLedgerStore) or
            not same_path or guard._disabled or ledger._disabled or
            not callable(getattr(port, "delivery_binding", None)) or
            not callable(getattr(port, "request_wake", None))
        )

    def _binding_matches(self, attempt) -> bool:
        try:
            binding = self.port.delivery_binding(attempt.nonce)
            observed = dict(binding) if isinstance(binding, Mapping) else None
        except Exception:
            return False
        expected = {
            "provider_id": attempt.provider_id,
            "provider_version": attempt.provider_version,
            "agent_id": attempt.agent_id,
            "model_id": attempt.model_id,
            "body_digest": attempt.body_digest,
        }
        return observed == expected

    def _finish(self, *, nonce: str, state: str, observed_at: str,
                result_class: str) -> str:
        outcome = self.ledger.transition(
            nonce=nonce, expected_state="submitting", new_state=state,
            observed_at=observed_at, result_class=result_class,
            evidence_digest=_evidence_digest(nonce, result_class),
        )
        if outcome == "updated":
            return state
        # Después de invocar el puerto nunca se habilita retry por un fallo al
        # persistir el acuse. El estado durable submitting será reconciliado.
        return "ambiguous"

    def submit(self, *, nonce: str, observed_at: str) -> str:
        """Avanza reserved y llama una vez al puerto; nunca reintenta."""
        if self._disabled:
            return "disabled"
        attempt = self.ledger.get(nonce)
        if attempt is None:
            return "disabled" if self.ledger._disabled else "not_found"
        if attempt.state != "reserved":
            return "conflict"
        if not self._binding_matches(attempt):
            return "mismatch"
        guard_result = self.guard.confirm_submission(
            nonce=attempt.nonce, receipt_digest=attempt.receipt_digest,
            target_id=attempt.target_id,
        )
        if guard_result != "allowed":
            return guard_result
        begin = self.ledger.transition(
            nonce=attempt.nonce, expected_state="reserved",
            new_state="submitting", observed_at=observed_at,
        )
        if begin != "updated":
            return begin

        # Segunda lectura después de persistir intención y justo antes del
        # efecto. Un kill switch observado aquí prueba que no se llamó al puerto.
        guard_result = self.guard.confirm_submission(
            nonce=attempt.nonce, receipt_digest=attempt.receipt_digest,
            target_id=attempt.target_id,
        )
        if guard_result != "allowed":
            return self._finish(
                nonce=attempt.nonce, state="failed", observed_at=observed_at,
                result_class="guard-blocked-before-io",
            )

        try:
            port_result: object = self.port.request_wake(
                attempt.target_id, attempt.nonce)
        except Exception:
            port_result = None
        if isinstance(port_result, str) and port_result == "queued":
            return self._finish(
                nonce=attempt.nonce, state="submitted", observed_at=observed_at,
                result_class="provider-queued",
            )
        if isinstance(port_result, str) and port_result in {"rejected", "unsupported"}:
            return self._finish(
                nonce=attempt.nonce, state="failed", observed_at=observed_at,
                result_class="provider-" + str(port_result),
            )
        return self._finish(
            nonce=attempt.nonce, state="ambiguous", observed_at=observed_at,
            result_class="provider-indeterminate",
        )


__all__ = ["WakeDeliveryCoordinator", "WakePort", "WakeSubmissionCoordinator"]
