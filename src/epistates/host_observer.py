"""Observador ``opencode-tmux/v1``: produce observaciones read-only para el preflight.

``observe_opencode_tmux`` **no** autoriza ni llama a ``evaluate_preflight``: sólo
reúne las 11 observaciones que el preflight consume. La separación es deliberada
— observar no es autorizar. El preflight decide ``ok``/``blocked``; el observer
sólo reporta el estado real del host.

Limitaciones locales v1 documentadas
------------------------------------

- ``observed_repository`` se deriva como ``basename`` del *git toplevel*
  reportado por Git. v1 **no** consulta la configuración de remotos: si el
  nombre del directorio difiere del repositorio esperado, el preflight bloquea
  con ``repository_mismatch``. Es una heurística local, no una identificación
  criptográfica del repositorio.
- ``observed_worktree`` pasa crudo desde ``git rev-parse --show-toplevel``: no
  se resuelven symlinks ni se normaliza para forzar coincidencia con
  ``target.worktree``.
- ``observed_cwd`` proviene del pane tmux y también pasa crudo.
- ``observed_at`` y ``observed_platform`` se inyectan: el observer no consulta
  el reloj ni una plataforma global.

Orden de operaciones (determinista, auditable)
----------------------------------------------

1. valida worktree (antes de subprocess), sesión, timestamp y plataforma;
2. ``git_toplevel`` -> ``observed_worktree`` y ``observed_repository`` (basename);
3. ``git_head`` -> ``observed_sha``;
4. ``git_branch`` -> ``observed_branch``;
5. ``git_status`` -> ``worktree_clean`` (vacío == limpio);
6. ``tmux_list_panes`` -> ``observed_cwd``, ``observed_command`` y ``pane_alive``.
"""

import os
from typing import Any, Mapping

from .contracts import ValidationError, validate_task_card
from .host_runner import (
    HostObserverError,
    HostRunner,
    validate_platform_token,
    validate_session_name,
    validate_utc_timestamp,
    validate_worktree_path,
)


_OBSERVED_KEYS = (
    "observed_repository",
    "observed_worktree",
    "observed_cwd",
    "observed_branch",
    "observed_sha",
    "worktree_clean",
    "observed_session_name",
    "pane_alive",
    "observed_command",
    "observed_platform",
    "observed_at",
)


def _extract_worktree(task_card: Any) -> str:
    """Extrae ``target.worktree`` sin confiar en la forma global de la tarjeta.

    La tarjeta se recibe ya validada por el caller; aquí sólo defendemos el
    campo que usaremos como ``cwd`` antes de cualquier subprocess.
    """
    if not isinstance(task_card, Mapping):
        raise HostObserverError("task_card debe ser un objeto JSON")
    target = task_card.get("target")
    if not isinstance(target, Mapping):
        raise HostObserverError("task_card.target debe ser un objeto JSON")
    return target.get("worktree")  # type: ignore[return-value]


def _repository_basename(toplevel: str) -> str:
    """Deriva el nombre del repositorio del toplevel sin seguir symlinks.

    El ``rstrip("/")`` sólo aplica al cálculo del basename; ``observed_worktree``
    se conserva crudo.
    """
    return os.path.basename(toplevel.rstrip("/"))


def observe_opencode_tmux(
    task_card: Mapping[str, Any],
    session_name: str,
    observed_at: str,
    platform_name: str,
    runner: HostRunner,
) -> dict:
    """Observa el host de forma read-only y devuelve las 11 claves del preflight.

    No consulta el reloj ni la plataforma global (``observed_at`` y
    ``platform_name`` se inyectan). No llama a ``evaluate_preflight`` ni entrega
    instrucciones al ejecutor.
    """
    try:
        validate_task_card(task_card)
    except ValidationError as error:
        # Tarjeta globalmente inválida: mensaje saneado, sin filtrar detalle.
        raise HostObserverError("task_card inválida") from error
    worktree = _extract_worktree(task_card)
    validate_worktree_path(worktree)
    validate_session_name(session_name)
    validate_utc_timestamp(observed_at)
    validate_platform_token(platform_name)
    if runner is None:
        raise HostObserverError("runner es requerido")

    observed_worktree = runner.git_toplevel(worktree)
    observed_repository = _repository_basename(observed_worktree)
    if not observed_repository:
        raise HostObserverError("observed_repository vacío")
    observed_sha = runner.git_head(worktree)
    observed_branch = runner.git_branch(worktree)
    status_text = runner.git_status(worktree)
    # Limpio == stdout exactamente vacío. Cualquier byte (incluido whitespace
    # anomalo) implica dirty: no usamos strip().
    worktree_clean = status_text == ""
    pane = runner.tmux_list_panes(session_name)

    result = {
        "observed_repository": observed_repository,
        "observed_worktree": observed_worktree,
        "observed_cwd": pane.current_path,
        "observed_branch": observed_branch,
        "observed_sha": observed_sha,
        "worktree_clean": worktree_clean,
        "observed_session_name": session_name,
        "pane_alive": not pane.dead,
        "observed_command": pane.current_command,
        "observed_platform": platform_name,
        "observed_at": observed_at,
    }
    # Defensa: exactamente las 11 claves esperadas, en orden canónico.
    if tuple(result) != _OBSERVED_KEYS:
        raise HostObserverError("observaciones con claves inesperadas")
    return result
