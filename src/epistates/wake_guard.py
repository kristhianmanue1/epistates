"""Reserva local de wake E4 sin proveedor ni efecto externo."""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Union


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_ID = re.compile(r"[a-z][a-z0-9-]{2,63}")
_NONCE = re.compile(r"[0-9a-f]{32}")


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp debe ser RFC3339 UTC")
    return datetime.fromisoformat(value[:-1] + "+00:00")


class WakeGuardStore:
    """Estado durable para reservar, nunca ejecutar, una futura solicitud."""

    def __init__(self, path: Union[str, Path], *, enabled: bool = False,
                 global_limit: int = 1, target_limit: int = 1,
                 window_seconds: int = 60):
        self.path, self._disabled = str(path), False
        if (not isinstance(enabled, bool) or any(not isinstance(value, int) or
                isinstance(value, bool) or value <= 0 for value in
                (global_limit, target_limit, window_seconds))):
            self._disabled = True
            return
        try:
            with sqlite3.connect(self.path) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS wake_policy ("
                           "id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, "
                           "global_limit INTEGER NOT NULL, target_limit INTEGER NOT NULL, "
                           "window_seconds INTEGER NOT NULL, killed INTEGER NOT NULL DEFAULT 0, "
                           "last_observed_at TEXT)")
                db.execute("CREATE TABLE IF NOT EXISTS wake_reservations ("
                           "nonce TEXT PRIMARY KEY, receipt_digest TEXT UNIQUE NOT NULL, "
                           "target_id TEXT NOT NULL, reserved_at TEXT NOT NULL, bucket INTEGER NOT NULL)")
                row = db.execute("SELECT enabled, global_limit, target_limit, window_seconds "
                                 "FROM wake_policy WHERE id=1").fetchone()
                expected = (int(enabled), global_limit, target_limit, window_seconds)
                if row is None:
                    db.execute("INSERT INTO wake_policy(id, enabled, global_limit, target_limit, window_seconds) "
                               "VALUES(1, ?, ?, ?, ?)", expected)
                elif tuple(row) != expected:
                    self._disabled = True
        except sqlite3.DatabaseError:
            self._disabled = True

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _prepare_reservation(self, *, receipt_digest: str, target_id: str,
                             nonce: str, dispatched_at: str, observed_at: str,
                             ttl_seconds: int):
        if self._disabled:
            return "disabled"
        if (not _DIGEST.fullmatch(receipt_digest or "") or
                not _ID.fullmatch(target_id or "") or not _NONCE.fullmatch(nonce or "") or
                not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or
                ttl_seconds <= 0):
            return "invalid"
        try:
            now, dispatched = _utc(observed_at), _utc(dispatched_at)
        except (ValueError, TypeError):
            return "invalid"
        if now < dispatched or (now - dispatched).total_seconds() > ttl_seconds:
            return "expired"
        return now

    def _reserve_in_transaction(self, db: sqlite3.Connection, *, receipt_digest: str,
                                target_id: str, nonce: str, observed_at: str,
                                now: datetime) -> str:
        enabled, global_limit, target_limit, window_seconds, killed, last = db.execute(
            "SELECT enabled, global_limit, target_limit, window_seconds, killed, last_observed_at "
            "FROM wake_policy WHERE id=1").fetchone()
        if not enabled or killed:
            return "disabled"
        if last is not None and now < _utc(last):
            return "expired"
        bucket = int(now.timestamp()) // window_seconds
        duplicate = db.execute(
            "SELECT 1 FROM wake_reservations WHERE nonce=? OR receipt_digest=?",
            (nonce, receipt_digest),
        ).fetchone()
        if duplicate:
            return "duplicate"
        global_count = db.execute(
            "SELECT COUNT(*) FROM wake_reservations WHERE bucket=?", (bucket,)
        ).fetchone()[0]
        target_count = db.execute(
            "SELECT COUNT(*) FROM wake_reservations WHERE bucket=? AND target_id=?",
            (bucket, target_id),
        ).fetchone()[0]
        if global_count >= global_limit or target_count >= target_limit:
            return "rate_limited"
        db.execute(
            "INSERT INTO wake_reservations(nonce, receipt_digest, target_id, reserved_at, bucket) "
            "VALUES (?, ?, ?, ?, ?)",
            (nonce, receipt_digest, target_id, observed_at, bucket),
        )
        db.execute("UPDATE wake_policy SET last_observed_at=? WHERE id=1", (observed_at,))
        return "reserved"

    def activate_kill_switch(self) -> str:
        """Activa de forma durable el kill switch; no existe desactivación aquí."""
        if self._disabled:
            return "disabled"
        try:
            with sqlite3.connect(self.path) as db:
                db.execute("UPDATE wake_policy SET killed=1 WHERE id=1")
        except sqlite3.DatabaseError:
            self._disabled = True
            return "disabled"
        return "disabled"

    def reserve(self, *, receipt_digest: str, target_id: str, nonce: str,
                dispatched_at: str, observed_at: str, ttl_seconds: int) -> str:
        """Reserva una cuota o devuelve un resultado cerrado; nunca hace wake."""
        prepared = self._prepare_reservation(
            receipt_digest=receipt_digest, target_id=target_id, nonce=nonce,
            dispatched_at=dispatched_at, observed_at=observed_at, ttl_seconds=ttl_seconds,
        )
        if isinstance(prepared, str):
            return prepared
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                return self._reserve_in_transaction(
                    db, receipt_digest=receipt_digest, target_id=target_id,
                    nonce=nonce, observed_at=observed_at, now=prepared,
                )
        except (sqlite3.DatabaseError, ValueError, TypeError):
            self._disabled = True
            return "disabled"


__all__ = ["WakeGuardStore"]
