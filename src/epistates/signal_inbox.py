"""Reconciliador acotado de bandeja local; no es watcher ni wake-up."""

import json
import os
import stat
from pathlib import Path
from typing import List

from .signal_receipts import SignalReceiptStore


class LocalSignalInbox:
    def __init__(self, root: Path, store: SignalReceiptStore, *, max_files: int = 64,
                 max_bytes: int = 4096):
        self.root, self.store, self.max_files, self.max_bytes = Path(root), store, max_files, max_bytes

    def _quarantine(self, path: Path) -> None:
        try:
            quarantine = self.root.parent / (self.root.name + ".quarantine")
            quarantine.mkdir(mode=0o700, exist_ok=True)
            os.replace(path, quarantine / path.name)
        except OSError:
            pass

    def reconcile(self, *, observed_at: str, ttl_seconds: int, kill_switch: bool = False) -> List[str]:
        """Consume a lo sumo ``max_files`` entradas regulares; nunca despierta nada."""
        try:
            entries = sorted(self.root.iterdir(), key=lambda item: item.name)[:self.max_files]
        except OSError:
            return ["disabled"]
        outcomes = []
        for path in entries:
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size > self.max_bytes:
                    outcomes.append("invalid")
                    self._quarantine(path)
                    continue
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        outcomes.append("invalid")
                        continue
                    data = os.read(fd, self.max_bytes + 1)
                finally:
                    os.close(fd)
                if len(data) > self.max_bytes:
                    outcomes.append("invalid")
                    continue
                context = json.loads(data.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                outcomes.append("invalid")
                self._quarantine(path)
                continue
            outcome = self.store.consume_once(context, observed_at=observed_at,
                                              ttl_seconds=ttl_seconds, kill_switch=kill_switch)
            outcomes.append(outcome)
            if outcome in {"accepted", "duplicate", "expired", "invalid"}:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return outcomes


__all__ = ["LocalSignalInbox"]
