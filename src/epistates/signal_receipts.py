"""Store local SQLite para consumo único de señales E3a.

No observa fuentes, no despierta tareas y no ejecuta inspección: sólo registra
una señal previamente ligada por el caller y devuelve un resultado cerrado.
"""

import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Union


class SignalReceiptError(ValueError):
    """La entrada no puede convertirse en un recibo local."""


_OUTCOMES = frozenset({"accepted", "duplicate", "expired", "invalid", "disabled"})
_ID = re.compile(r"[a-z][a-z0-9-]{2,63}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SignalReceiptError("timestamp debe ser RFC3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SignalReceiptError("timestamp inválido") from exc


class SignalReceiptStore:
    """Consumo único por identidad de ejecución, respaldado por SQLite."""

    def __init__(self, path: Union[str, Path]):
        self.path = str(path)
        self._disabled = False
        try:
            with sqlite3.connect(self.path) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS consumed_signals ("
                           "receipt_key TEXT PRIMARY KEY, received_at TEXT NOT NULL)")
        except sqlite3.DatabaseError:
            self._disabled = True

    def consume_once(self, context: Mapping[str, str], *, observed_at: str,
                     ttl_seconds: int, kill_switch: bool = False) -> str:
        """Devuelve un outcome; sólo la primera inserción válida es accepted."""
        if kill_switch or self._disabled:
            return "disabled"
        required = {"task_id", "run_id", "attempt_id", "adapter_id", "session_name", "dispatch_receipt_digest", "event_type", "dispatched_at", "current_state"}
        if not isinstance(context, Mapping) or set(context) != required:
            return "invalid"
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
            return "invalid"
        values = [context[key] for key in required]
        if any(not isinstance(value, str) or not value for value in values):
            return "invalid"
        if context["event_type"] != "external_completion":
            return "invalid"
        if context["current_state"] != "WAITING_EXTERNAL":
            return "invalid"
        if any(not _ID.fullmatch(context[key]) for key in ("task_id", "run_id", "attempt_id", "adapter_id", "session_name")):
            return "invalid"
        if not _DIGEST.fullmatch(context["dispatch_receipt_digest"]):
            return "invalid"
        try:
            now, dispatched = _utc(observed_at), _utc(context["dispatched_at"])
        except SignalReceiptError:
            return "invalid"
        if now < dispatched or (now - dispatched).total_seconds() > ttl_seconds:
            return "expired"
        key = "|".join(context[key] for key in ("task_id", "run_id", "attempt_id", "adapter_id", "session_name", "dispatch_receipt_digest", "event_type"))
        try:
            with sqlite3.connect(self.path, timeout=5) as db:
                try:
                    db.execute("INSERT INTO consumed_signals(receipt_key, received_at) VALUES (?, ?)", (key, observed_at))
                except sqlite3.IntegrityError:
                    return "duplicate"
        except sqlite3.DatabaseError:
            return "disabled"
        return "accepted"


__all__ = ["SignalReceiptError", "SignalReceiptStore"]
