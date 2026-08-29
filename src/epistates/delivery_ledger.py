"""Ledger durable E4 sin transporte, reconciliación ni wake."""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_RESULT_CLASS = re.compile(r"[a-z][a-z0-9._-]{2,63}")
_STATES = frozenset({
    "reserved", "submitting", "submitted", "completed", "failed", "ambiguous",
})
_TRANSITIONS = {
    "reserved": frozenset({"submitting", "failed"}),
    # `failed` desde submitting sólo cubre un aborto comprobado antes de
    # invocar el puerto (p. ej. kill switch reactivado). Tras intentar I/O,
    # cualquier fallo sin acuse inequívoco es `ambiguous`.
    "submitting": frozenset({"submitted", "failed", "ambiguous"}),
    "submitted": frozenset({"completed", "failed", "ambiguous"}),
}
_SCHEMA_VERSION = 1


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp debe ser RFC3339 UTC")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() is None:
        raise ValueError("timestamp debe incluir zona UTC")
    return parsed


def _identifier(value: str) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


@dataclass(frozen=True)
class DeliveryAttempt:
    nonce: str
    receipt_digest: str
    target_id: str
    provider_id: str
    provider_version: str
    agent_id: str
    model_id: str
    body_digest: str
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DeliveryEvent:
    sequence: int
    from_state: Optional[str]
    to_state: str
    observed_at: str
    result_class: Optional[str]
    evidence_digest: Optional[str]


class DeliveryLedgerStore:
    """Persiste intentos y transiciones E4; nunca realiza efectos externos."""

    def __init__(self, path: Union[str, Path]):
        self.path = str(path)
        self._disabled = not self.path or self.path == ":memory:"
        if self._disabled:
            return
        try:
            with self._connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS delivery_meta ("
                           "id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL)")
                row = db.execute(
                    "SELECT schema_version FROM delivery_meta WHERE id=1"
                ).fetchone()
                if row is not None and row[0] != _SCHEMA_VERSION:
                    self._disabled = True
                    return
                if row is None:
                    db.execute(
                        "INSERT INTO delivery_meta(id, schema_version) VALUES(1, ?)",
                        (_SCHEMA_VERSION,),
                    )
                db.execute("CREATE TABLE IF NOT EXISTS delivery_attempts ("
                           "nonce TEXT PRIMARY KEY, receipt_digest TEXT UNIQUE NOT NULL, "
                           "target_id TEXT NOT NULL, provider_id TEXT NOT NULL, "
                           "provider_version TEXT NOT NULL, "
                           "agent_id TEXT NOT NULL, model_id TEXT NOT NULL, "
                           "body_digest TEXT NOT NULL, state TEXT NOT NULL, "
                           "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS delivery_events ("
                           "nonce TEXT NOT NULL, sequence INTEGER NOT NULL, "
                           "from_state TEXT, to_state TEXT NOT NULL, observed_at TEXT NOT NULL, "
                           "result_class TEXT, evidence_digest TEXT, "
                           "PRIMARY KEY(nonce, sequence), "
                           "FOREIGN KEY(nonce) REFERENCES delivery_attempts(nonce))")
        except (OSError, sqlite3.DatabaseError):
            self._disabled = True

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def create_reserved(self, *, nonce: str, receipt_digest: str, target_id: str,
                        provider_id: str, provider_version: str, agent_id: str, model_id: str,
                        body_digest: str, observed_at: str) -> str:
        """Crea un intento reservado; un replay byte-equivalente es idempotente."""
        expected = self._prepare_reserved(
            nonce=nonce, receipt_digest=receipt_digest, target_id=target_id,
            provider_id=provider_id, provider_version=provider_version,
            agent_id=agent_id, model_id=model_id, body_digest=body_digest,
            observed_at=observed_at,
        )
        if isinstance(expected, str):
            return expected
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                return self._create_reserved_in_transaction(db, expected)
        except (OSError, sqlite3.DatabaseError):
            self._disabled = True
            return "disabled"

    def _prepare_reserved(self, *, nonce: str, receipt_digest: str, target_id: str,
                          provider_id: str, provider_version: str, agent_id: str,
                          model_id: str, body_digest: str, observed_at: str):
        values = (target_id, provider_id, provider_version, agent_id, model_id)
        if (self._disabled or not isinstance(nonce, str) or not _NONCE.fullmatch(nonce) or
                not isinstance(receipt_digest, str) or not _DIGEST.fullmatch(receipt_digest) or
                not isinstance(body_digest, str) or not _DIGEST.fullmatch(body_digest) or
                not all(_identifier(value) for value in values)):
            return "disabled" if self._disabled else "invalid"
        try:
            _utc(observed_at)
        except (TypeError, ValueError):
            return "invalid"
        expected = (
            nonce, receipt_digest, target_id, provider_id, provider_version, agent_id, model_id,
            body_digest, "reserved", observed_at, observed_at,
        )
        return expected

    def _create_reserved_in_transaction(self, db: sqlite3.Connection, expected: tuple,
                                        *, idempotent_replay: bool = True) -> str:
        nonce, receipt_digest = expected[:2]
        row = db.execute(
            "SELECT nonce, receipt_digest, target_id, provider_id, provider_version, agent_id, "
            "model_id, body_digest, state, created_at, updated_at "
            "FROM delivery_attempts WHERE nonce=? OR receipt_digest=?",
            (nonce, receipt_digest),
        ).fetchone()
        if row is not None:
            if idempotent_replay and tuple(row) == expected:
                return "reserved"
            return "duplicate"
        db.execute(
            "INSERT INTO delivery_attempts(nonce, receipt_digest, target_id, "
            "provider_id, provider_version, agent_id, model_id, body_digest, state, "
            "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            expected,
        )
        db.execute(
            "INSERT INTO delivery_events(nonce, sequence, from_state, to_state, observed_at) "
            "VALUES(?, 0, NULL, 'reserved', ?)",
            (nonce, expected[-1]),
        )
        return "reserved"

    def transition(self, *, nonce: str, expected_state: str, new_state: str,
                   observed_at: str, result_class: Optional[str] = None,
                   evidence_digest: Optional[str] = None) -> str:
        """Aplica una transición permitida mediante compare-and-swap durable."""
        if self._disabled:
            return "disabled"
        if (not isinstance(nonce, str) or not _NONCE.fullmatch(nonce) or
                expected_state not in _STATES or new_state not in _STATES or
                new_state not in _TRANSITIONS.get(expected_state, frozenset())):
            return "invalid"
        has_evidence = (
            isinstance(result_class, str) and _RESULT_CLASS.fullmatch(result_class) is not None and
            isinstance(evidence_digest, str) and _DIGEST.fullmatch(evidence_digest) is not None
        )
        if (new_state == "submitting" and (result_class is not None or evidence_digest is not None)) or (
                new_state != "submitting" and not has_evidence):
            return "invalid"
        try:
            now = _utc(observed_at)
        except (TypeError, ValueError):
            return "invalid"
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT state, updated_at FROM delivery_attempts WHERE nonce=?", (nonce,)
                ).fetchone()
                if row is None:
                    return "not_found"
                current_state, previous_at = row
                if current_state != expected_state:
                    return "conflict"
                if now < _utc(previous_at):
                    return "invalid"
                changed = db.execute(
                    "UPDATE delivery_attempts SET state=?, updated_at=? "
                    "WHERE nonce=? AND state=?",
                    (new_state, observed_at, nonce, expected_state),
                ).rowcount
                if changed != 1:
                    return "conflict"
                sequence = db.execute(
                    "SELECT COALESCE(MAX(sequence), -1) + 1 FROM delivery_events WHERE nonce=?",
                    (nonce,),
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO delivery_events(nonce, sequence, from_state, to_state, "
                    "observed_at, result_class, evidence_digest) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (nonce, sequence, expected_state, new_state, observed_at,
                     result_class, evidence_digest),
                )
        except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
            self._disabled = True
            return "disabled"
        return "updated"

    def get(self, nonce: str) -> Optional[DeliveryAttempt]:
        """Devuelve el estado durable actual sin transicionar ni reconciliar."""
        if self._disabled or not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
            return None
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT nonce, receipt_digest, target_id, provider_id, provider_version, agent_id, "
                    "model_id, body_digest, state, created_at, updated_at "
                    "FROM delivery_attempts WHERE nonce=?", (nonce,)
                ).fetchone()
        except (OSError, sqlite3.DatabaseError):
            self._disabled = True
            return None
        return DeliveryAttempt(*row) if row is not None else None

    def history(self, nonce: str) -> Tuple[DeliveryEvent, ...]:
        """Devuelve el historial append-only en orden; no interpreta resultados."""
        if self._disabled or not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
            return ()
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT sequence, from_state, to_state, observed_at, result_class, "
                    "evidence_digest FROM delivery_events WHERE nonce=? ORDER BY sequence",
                    (nonce,),
                ).fetchall()
        except (OSError, sqlite3.DatabaseError):
            self._disabled = True
            return ()
        return tuple(DeliveryEvent(*row) for row in rows)


__all__ = ["DeliveryAttempt", "DeliveryEvent", "DeliveryLedgerStore"]
