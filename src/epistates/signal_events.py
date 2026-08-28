"""Pistas macOS de filesystem para reconciliar una bandeja local.

El adaptador no es un daemon ni una API de wake. Una pista sólo provoca una
llamada al reconciliador suministrado por el controlador y su resultado se
descarta. El controlador debe reconciliar al iniciar: kqueue puede coalescer o
perder eventos y, por tanto, nunca es la fuente de verdad.
"""

import math
import os
import select
from pathlib import Path
from typing import Any, Callable, Optional, Union


class SignalEventError(RuntimeError):
    """El adaptador local no puede vigilar el directorio indicado."""


class KqueueSignalAdapter:
    """Una sola espera kqueue que sólo pide reconciliación local.

    ``reconcile`` no recibe datos del evento y su retorno no se observa. Un
    ``True`` significa únicamente que kqueue entregó una pista (o que dejó de
    poder observar el descriptor); nunca significa aceptación ni permiso.
    """

    def __init__(self, root: Union[str, Path], reconcile: Callable[[], Any]):
        if not callable(reconcile):
            raise TypeError("reconcile debe ser invocable")
        if not hasattr(select, "kqueue"):
            raise SignalEventError("kqueue sólo está disponible en macOS")
        self.root = Path(root)
        self._reconcile = reconcile
        self._closed = False
        self._fd: Optional[int] = None
        self._kqueue: Any = None
        try:
            self._fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            self._kqueue = select.kqueue()
            change = select.kevent(
                self._fd,
                filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=(select.KQ_NOTE_WRITE | select.KQ_NOTE_RENAME |
                        select.KQ_NOTE_DELETE | select.KQ_NOTE_REVOKE),
            )
            self._kqueue.control([change], 0, 0)
        except (OSError, ValueError) as exc:
            self.close()
            raise SignalEventError("no se puede vigilar la bandeja local") from exc

    def __enter__(self) -> "KqueueSignalAdapter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        """Libera descriptores; es idempotente y no reconcilia."""
        if self._closed:
            return
        self._closed = True
        if self._kqueue is not None:
            self._kqueue.close()
            self._kqueue = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def wait_once(self, timeout_seconds: float) -> bool:
        """Espera una pista y, si llega, llama sólo a ``reconcile`` una vez."""
        if (isinstance(timeout_seconds, bool) or
                not isinstance(timeout_seconds, (int, float)) or
                not math.isfinite(timeout_seconds) or timeout_seconds < 0 or
                timeout_seconds > 60):
            raise ValueError("timeout_seconds debe estar entre 0 y 60")
        if self._closed or self._kqueue is None:
            raise SignalEventError("adaptador cerrado")
        try:
            events = self._kqueue.control(None, 1, timeout_seconds)
        except OSError:
            # Un descriptor revocado o directorio desaparecido exige una
            # reconciliación fail-closed, no una decisión ni una reactivación.
            events = [object()]
        if not events:
            return False
        self._reconcile()
        return True


__all__ = ["KqueueSignalAdapter", "SignalEventError"]
