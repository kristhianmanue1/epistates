"""Runner read-only inyectable para la observación limitada del host.

Este módulo ejecuta un conjunto *cerrado* de operaciones de observación contra
Git y tmux. No acepta argv arbitrario del caller: cada operación construye su
propio argv exacto y valida sus entradas antes de invocar ``subprocess``.

La observación es estrictamente read-only: no usa ``tmux send-keys``,
``capture-pane``, ``kill-session`` ni crea sesiones. Sólo lee estado de Git
(``rev-parse``, ``branch --show-current``, ``status --porcelain=v1``) y lista
los panes de una sesión tmux *existente*.

Seguridad y honestidad
----------------------

- ``subprocess`` se ejecuta con ``shell=False``, ``stdin=DEVNULL`` y argv list.
- El entorno es **mínimo y construido desde cero**: no hereda variables del
  caller (en particular HOME, PATH, GIT_* y TMUX_* se excluyen). Se fija locale
  ``C`` y los flags ``GIT_OPTIONAL_LOCKS=0``, ``GIT_CONFIG_NOSYSTEM=1`` y
  ``GIT_CONFIG_GLOBAL=/dev/null`` para evitar que el entorno del caller redirija
  las observaciones o provoque escrituras (index locks, config global/system).
  Los executables son absolutos: no se depende de PATH.
- Toda salida se captura como bytes y se decodifica UTF-8 estricto.
- Se falla cerrado ante: timeout, executable ausente o inaccesible (OSError,
  incluido PermissionError), exit no cero, stderr no vacío en exit 0, salida
  combinada sobre el límite (comprobada antes de interpretar exit), byte NUL,
  UTF-8 inválido o forma inesperada.
- Los mensajes de error **no** incluyen stdout/stderr (potencialmente
  sensibles): sólo describen la categoría del fallo.
- ``max_output_bytes`` se aplica *después* de capturar la salida del proceso en
  memoria (``subprocess.run`` con pipes). Esto **no** es aislamiento de memoria
  del SO: el proceso hijo pudo producir más datos de los que conservamos; la
  salvaguarda sólo impide devolverlos o decodificarlos. El caller debe elegir un
  límite modesto; el runner impone además un techo razonable.
- ``timeout_seconds`` debe ser un número finito en el rango cerrado
  ``(0, 60]``: se rechazan NaN, infinito y valores enormes.
"""

import math
import re
import subprocess
from datetime import datetime, timezone
from os.path import isabs, normpath
from typing import NamedTuple, Protocol


class HostObserverError(ValueError):
    """La observación read-only no pudo completarse de forma verificable."""


# Sesión tmux: identificador cerrado. Excluye los metacaracteres de target tmux
# (':', '.', '/'), shell, espacios y control. Suficiente para argv seguro con
# ``-t SESSION`` como elemento independiente del argv list.
_SESSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

# Plataforma canónica H3 Slice1 (adapter.platforms): token lowercase.
_PLATFORM_TOKEN_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,31}")

# SHA hex de Git (40..64), mismo criterio que el preflight.
_SHA_PATTERN = re.compile(r"[0-9a-f]{40,64}")

# RFC3339 UTC con terminador Z (mismo criterio que el preflight).
_UTC_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z"
)

# Techo razonable para ``max_output_bytes``: el caller acota, pero impedimos un
# valor absurdo que desactivaría la salvaguarda post-capture.
_MAX_OUTPUT_CEILING = 16 * 1024 * 1024

# Rango cerrado y documentado para ``timeout_seconds`` (segundos).
_TIMEOUT_FLOOR = 0.0
_TIMEOUT_CEILING = 60.0

# Entorno mínimo construido desde cero (no hereda nada del caller).
# Los executables son absolutos: no se incluye PATH.
_MINIMAL_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}

# Delimitador de campos para ``tmux list-panes -F``. Es **printable ASCII**
# (``|``) porque tmux 3.6a sanitiza los caracteres de control del formato: con
# un TAB literal, tmux devuelve ``_`` en su lugar (p. ej.
# ``b"0_opencode_/path\n"``) y el framing por TAB colapsa a un solo campo. ``|``
# es lo bastante distintivo: no aparece en nombres de comando ni en paths reales
# del worktree; una colisión (``|`` dentro de un valor) produce más de 3 campos
# y se rechaza por fail-closed en lugar de malinterpretarse.
_TMUX_FIELD_SEP = "|"
_TMUX_FORMAT = (
    "#{pane_dead}" + _TMUX_FIELD_SEP
    + "#{pane_current_command}" + _TMUX_FIELD_SEP
    + "#{pane_current_path}"
)


class PaneObservation(NamedTuple):
    """Observación de un único pane tmux, ya validada por el runner."""

    dead: bool
    current_command: str
    current_path: str


class HostRunner(Protocol):
    """Contrato del runner read-only inyectable.

    Las operaciones son cerradas: ninguna acepta argv del caller. Una
    implementación de producción usa ``subprocess``; los tests inyectan un fake
    determinista que registra las llamadas.
    """

    def git_toplevel(self, cwd: str) -> str: ...
    def git_head(self, cwd: str) -> str: ...
    def git_branch(self, cwd: str) -> str: ...
    def git_status(self, cwd: str) -> str: ...
    def tmux_list_panes(self, session_name: str) -> PaneObservation: ...


def validate_session_name(value: object) -> str:
    """Exige un nombre de sesión tmux cerrado y seguro para argv."""
    if not isinstance(value, str) or not _SESSION_PATTERN.fullmatch(value):
        raise HostObserverError("session_name debe ser un identificador cerrado")
    return value


def validate_worktree_path(value: object) -> str:
    """Validación léxica de un worktree absoluto, normalizado y distinto de raíz.

    No resuelve symlinks (no sigue enlaces): sólo comprueba la forma de la
    ruta. Es una defensa antes de pasarla como ``cwd`` a ``subprocess``.
    """
    if not isinstance(value, str):
        raise HostObserverError("worktree debe ser una ruta absoluta")
    segments = value.split("/")
    if (not isabs(value) or value == "/" or value.startswith("//")
            or "." in segments or ".." in segments or normpath(value) != value):
        raise HostObserverError(
            "worktree debe ser absoluto, normalizado y distinto de raíz"
        )
    return value


def validate_platform_token(value: object) -> str:
    """Exige un token de plataforma canónico lowercase."""
    if not isinstance(value, str) or not _PLATFORM_TOKEN_PATTERN.fullmatch(value):
        raise HostObserverError("platform_name debe ser un token canónico lowercase")
    return value


def validate_utc_timestamp(value: object) -> str:
    """Exige un timestamp RFC3339 UTC terminado en Z y fecha/hora reales.

    El regex descarta formas erróneas; ``datetime`` descarta fechas inválidas
    que el regex acepta (p. ej. ``2026-99-99T00:00:00Z``). Exige además UTC.
    """
    if not isinstance(value, str) or not _UTC_PATTERN.fullmatch(value):
        raise HostObserverError("observed_at debe ser RFC3339 UTC terminado en Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise HostObserverError("observed_at debe ser RFC3339 UTC válido") from error
    if parsed.tzinfo != timezone.utc:
        raise HostObserverError("observed_at debe estar en UTC")
    return value


def _require_absolute_executable(path: object, name: str) -> str:
    """Ruta de executable absoluta, normalizada y sin NUL ni raíz.

    No exige existencia (el constructor no prueba el filesystem): la ausencia o
    inaccesibilidad se reporta como ``HostObserverError`` al ejecutar.
    """
    if not isinstance(path, str):
        raise HostObserverError(f"{name} debe ser una ruta absoluta")
    if "\0" in path:
        raise HostObserverError(f"{name} no debe contener NUL")
    segments = path.split("/")
    if path == "/":
        raise HostObserverError(f"{name} no debe ser raíz")
    if (not isabs(path) or path.startswith("//")
            or "." in segments or ".." in segments or normpath(path) != path):
        raise HostObserverError(f"{name} debe ser absoluta y normalizada")
    return path


def _decode_utf8(raw: bytes, what: str) -> str:
    """Decodifica bytes UTF-8 estricto; falla cerrado ante NUL o UTF-8 inválido."""
    if b"\0" in raw:
        raise HostObserverError(f"{what} con byte NUL")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HostObserverError(f"{what} con UTF-8 inválido") from error


def _has_control_char(value: str) -> bool:
    """Cierto si la cadena contiene un carácter ASCII de control (0x00-0x1F o DEL).

    Los tabs y newlines ya rompen el framing del formato tmux; aquí cubrimos
    además CR, DEL y cualquier otro control que no afecta al split por tab.
    """
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)


class ProductionHostRunner:
    """Runner de producción que ejecuta ``subprocess`` read-only contra git y tmux.

    Recibe rutas absolutas confiables a los executables (no las busca en
    ``PATH``), un ``timeout_seconds`` positivo y un ``max_output_bytes`` acotado.
    Todas las operaciones construyen argv internamente; el caller nunca aporta
    argv.
    """

    def __init__(self, git_path, tmux_path, timeout_seconds, max_output_bytes):
        self._git = _require_absolute_executable(git_path, "git_path")
        self._tmux = _require_absolute_executable(tmux_path, "tmux_path")
        if (not isinstance(timeout_seconds, (int, float))
                or isinstance(timeout_seconds, bool)
                or not math.isfinite(timeout_seconds)
                or not (_TIMEOUT_FLOOR < timeout_seconds <= _TIMEOUT_CEILING)):
            raise HostObserverError(
                f"timeout_seconds debe ser un número finito en (0, {_TIMEOUT_CEILING:g}]"
            )
        if (not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool)
                or not (0 < max_output_bytes <= _MAX_OUTPUT_CEILING)):
            raise HostObserverError("max_output_bytes debe ser un entero acotado positivo")
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes
        # Entorno mínimo inmutable construido desde cero (no hereda nada).
        self._env = dict(_MINIMAL_ENV)

    # -- subprocess de bajo nivel ----------------------------------------

    def _run(self, argv, cwd):
        """Ejecuta argv cerrado (shell=False, stdin DEVNULL, env mínimo).

        Devuelve stdout bytes. Falla cerrado ante timeout, OSError (incluido
        PermissionError y executable ausente), salida combinada sobre el límite
        (comprobada antes de interpretar exit), exit no cero o stderr no vacío
        en exit 0. No incluye stdout/stderr en los errores.
        """
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                timeout=self._timeout,
                check=False,
                shell=False,
                env=self._env,
            )
        except subprocess.TimeoutExpired as error:
            raise HostObserverError("timeout agotado") from error
        except OSError as error:
            # FileNotFoundError (executable ausente), PermissionError y demás.
            raise HostObserverError("executable ausente o inaccesible") from error
        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        # Overflow ANTES de interpretar exit; no inspeccionamos contenido.
        if len(stdout) + len(stderr) > self._max_output:
            raise HostObserverError("salida combinada sobre el límite")
        if completed.returncode != 0:
            raise HostObserverError("exit no cero")
        # stderr no vacío con exit 0 es anomal para observación read-only.
        if stderr:
            raise HostObserverError("stderr no vacío")
        return stdout

    @staticmethod
    def _decode_one_line(raw, what):
        """Decodifica bytes a una sola línea: a lo sumo un LF final, sin CR/LF.

        Acepta ``"sha"`` y ``"sha\\n"``; rechaza dos o más saltos finales,
        saltos incrustados y cualquier CR (p. ej. CRLF).
        """
        text = _decode_utf8(raw, what)
        if text.endswith("\n"):
            text = text[:-1]
        if "\n" in text or "\r" in text:
            raise HostObserverError(f"{what} con forma inesperada")
        return text

    # -- operaciones cerradas de Git -------------------------------------

    def git_toplevel(self, cwd):
        validate_worktree_path(cwd)
        argv = [self._git, "rev-parse", "--show-toplevel"]
        text = self._decode_one_line(self._run(argv, cwd), "git_toplevel")
        if not text:
            raise HostObserverError("git_toplevel vacío")
        return text

    def git_head(self, cwd):
        validate_worktree_path(cwd)
        argv = [self._git, "rev-parse", "HEAD"]
        text = self._decode_one_line(self._run(argv, cwd), "git_head")
        if not _SHA_PATTERN.fullmatch(text):
            raise HostObserverError("git_head con forma inesperada")
        return text

    def git_branch(self, cwd):
        validate_worktree_path(cwd)
        argv = [self._git, "branch", "--show-current"]
        text = self._decode_one_line(self._run(argv, cwd), "git_branch")
        if not text:
            # Detached HEAD: ``--show-current`` no devuelve rama. Forma
            # inesperada para esta operación cerrada.
            raise HostObserverError("git_branch vacío (detached HEAD)")
        return text

    def git_status(self, cwd):
        validate_worktree_path(cwd)
        argv = [self._git, "status", "--porcelain=v1", "--untracked-files=normal"]
        raw = self._run(argv, cwd)
        # Conservamos el texto crudo (incluido el salto final) para que el
        # observer decida limpieza sin normalización sensible.
        return _decode_utf8(raw, "git_status")

    # -- operación cerrada de tmux ---------------------------------------

    def tmux_list_panes(self, session_name):
        validate_session_name(session_name)
        argv = [
            self._tmux, "list-panes", "-t", session_name, "-F", _TMUX_FORMAT,
        ]
        # Framing printable (``|``): tmux 3.6a sanitiza TAB a ``_``; un
        # delimitador de control rompería el split. tmux no requiere cwd del
        # worktree; list-panes opera sobre la sesión. Pasamos ``cwd=None``.
        text = _decode_utf8(self._run(argv, None), "tmux_list_panes")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if len(lines) != 1:
            raise HostObserverError("tmux_list_panes exige exactamente un pane")
        fields = lines[0].split(_TMUX_FIELD_SEP)
        if len(fields) != 3:
            raise HostObserverError("tmux_list_panes exige tres campos")
        dead_flag, command, path = fields
        if dead_flag == "0":
            dead = False
        elif dead_flag == "1":
            dead = True
        else:
            raise HostObserverError("pane_dead con forma inesperada")
        if not command or not path:
            raise HostObserverError("tmux_list_panes con campo vacío")
        if _has_control_char(command) or _has_control_char(path):
            raise HostObserverError("tmux_list_panes con carácter de control")
        return PaneObservation(dead=dead, current_command=command, current_path=path)
