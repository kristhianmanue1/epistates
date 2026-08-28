"""Reserva atómica de guard y ledger E4, sin ejecutar wake."""

import sqlite3
from pathlib import Path

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


__all__ = ["WakeDeliveryCoordinator"]
