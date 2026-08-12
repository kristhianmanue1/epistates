"""Runner read-only inyectable para la inspección post-ejecución.

Frontera **separada** del ``HostRunner`` (observación) y del ``LiteralDispatcher``
(escritura). Expone operaciones cerradas: una única captura ``capture-pane``
acotada y checks resueltos desde un catálogo confiable. Ninguna operación acepta
argv del caller: cada una construye su propio argv exacto y valida sus entradas.

Disciplina de subprocess (producción)
-------------------------------------

- ``shell=False``, ``stdin=DEVNULL``, argv list y executables absolutos.
- Entorno mínimo construido desde cero (sin ``PATH``/``HOME``/``TMUX*``/``GIT_*``
  hostiles; locale ``C`` y flags Git read-only para los checks de Git).
- Toda salida se captura como bytes y se decodifica UTF-8 estricto.
- Se falla cerrado ante timeout, executable ausente/inaccesible (OSError), salida
  combinada sobre el límite, byte NUL o UTF-8 inválido.
- Los mensajes de error **no** incluyen stdout/stderr: sólo la categoría.
- ``max_output_bytes`` se aplica *después* de capturar (no es aislamiento de
  memoria del SO); el caller elige un límite modesto y el runner impone un techo.
- ``timeout_seconds`` debe ser un número finito en ``(0, 60]``.

capture-pane: exactamente una llamada, rango acotado, join explícito
-----------------------------------------------------------------------

- La captura usa ``-J`` (join de líneas envueltas), ``-p`` (a stdout) y
  ``-S -{capture_lines}`` (scrollback acotado). El contenido **nunca** sale del
  runner: sólo se devuelven digest y longitud. El recibo de inspección no
  persiste contenido libre.

Checks: catálogo cerrado, pass/fail por exit code
-------------------------------------------------

- ``git_status``: ``git -c core.fsmonitor=false status --porcelain=v1 --``.
  pass = exit 0 (evidencia).
- ``diff_check``: ``git -c core.fsmonitor=false diff --no-ext-diff --check HEAD --``.
  Cubre staged + unstado en una sola llamada read-only; excluye external diff.
  pass = exit 0, fail = exit 1.
- ``unit_tests``: ``python -m unittest discover`` con ``PYTHONPATH=<worktree>/src``
  y ``PYTHONNOUSERSITE=1`` para ligar inequívocamente el worktree (no el checkout
  principal). pass = exit 0, fail = non-zero.
- Un check que retorna ``fail`` es un **resultado válido**, no un error. Sólo
  timeout/OSError/UTF-8 inválido/overflow son errores indeterminados.

Entornos deterministas
----------------------

- Todos los entornos incluyen ``TMPDIR=/tmp``: en macOS el runtime de libsystem
  emite un warning a stderr por ``confstr(_CS_DARWIN_USER_TEMP_DIR)`` cuando el
  entorno es demasiado mínimo; un stderr no vacío rompería la observación
  estricta sin que el contenido fuera relevante. ``/tmp`` es estándar y no es
  config hostil del caller.
- ``unit_tests`` usa ``PYTHONPATH`` por instancia (construido en ``__init__``
  desde el worktree) para que el intérprete absoluto resuelva ``epistates`` desde
  **este** worktree, no desde un editable install del checkout principal.
"""


import hashlib
import math
import subprocess
from os.path import isabs, normpath
from typing import NamedTuple, Protocol

from .host_runner import HostObserverError, validate_session_name, validate_worktree_path


class ReviewRunnerError(ValueError):
    """La inspección read-only no pudo completarse de forma verificable."""


class IndeterminateReviewError(ValueError):
    """Captura o check intentado y fallado ambiguamente. NO reintenta."""


_MAX_OUTPUT_CEILING = 16 * 1024 * 1024
_TIMEOUT_FLOOR = 0.0
_TIMEOUT_CEILING = 60.0

# Rango acotado de scrollback para capture-pane (líneas).
_CAPTURE_LINES_FLOOR = 1
_CAPTURE_LINES_CEILING = 200

# Catálogo cerrado de checks. El caller aporta sólo el check_id; el argv se
# construye internamente. Nunca argv de tarjeta/agente.
_CHECK_CATALOG = frozenset({"git_status", "diff_check", "unit_tests"})

# Entorno mínimo para captura tmux (sin PATH/HOME/TMUX). TMPDIR evita el
# warning de libsystem en macOS bajo entorno mínimo.
_CAPTURE_ENV = {"LC_ALL": "C", "LANG": "C", "TMPDIR": "/tmp"}

# Entorno mínimo para checks de Git (read-only, sin config global/system).
# TMPDIR silencia el warning de confstr(_CS_DARWIN_USER_TEMP_DIR) en macOS.
_GIT_CHECK_ENV = {
    "LC_ALL": "C", "LANG": "C", "TMPDIR": "/tmp",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}

# Claves base para el entorno de unit_tests; PYTHONPATH se añade por instancia.
_UNIT_TEST_ENV_BASE = {"LC_ALL": "C", "LANG": "C", "TMPDIR": "/tmp"}


class CaptureOutcome(NamedTuple):
    """Metadata de una captura acotada; el contenido NUNCA sale del runner."""

    digest: str
    length_utf8: int
    capture_lines: int


class CheckOutcome(NamedTuple):
    """Resultado de un check cerrado: pass/fail + digest + longitud."""

    check_id: str
    status: str  # "pass" | "fail"
    digest: str
    length_utf8: int


class ReviewRunner(Protocol):
    """Contrato del runner de inspección inyectable y read-only.

    Las operaciones son cerradas: ninguna acepta argv del caller. Una
    implementación de producción usa ``subprocess`` (capture-pane + checks); los
    tests inyectan un fake determinista que registra las llamadas.
    """

    def capture_once(self, session_name: str) -> CaptureOutcome: ...
    def run_check(self, check_id: str) -> CheckOutcome: ...


# ---------------------------------------------------------------------------
# Helpers de validación y saneamiento (propios de esta frontera).
# ---------------------------------------------------------------------------


def _require_absolute_executable(path: object, name: str) -> str:
    if not isinstance(path, str):
        raise ReviewRunnerError(f"{name} debe ser una ruta absoluta")
    if "\0" in path:
        raise ReviewRunnerError(f"{name} no debe contener NUL")
    segments = path.split("/")
    if path == "/":
        raise ReviewRunnerError(f"{name} no debe ser raíz")
    if (not isabs(path) or path.startswith("//")
            or "." in segments or ".." in segments or normpath(path) != path):
        raise ReviewRunnerError(f"{name} debe ser absoluta y normalizada")
    return path


def _decode_utf8(raw: bytes, what: str) -> str:
    if b"\0" in raw:
        raise IndeterminateReviewError(f"{what} con byte NUL")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IndeterminateReviewError(f"{what} con UTF-8 inválido") from error


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _length(text: str) -> int:
    return len(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Runner de producción.
# ---------------------------------------------------------------------------


class TmuxReviewRunner:
    """Runner de producción: una captura ``capture-pane`` acotada + checks.

    Recibe rutas absolutas confiables a los executables (no las busca en
    ``PATH``), el worktree absoluto, un ``timeout_seconds`` positivo, un
    ``max_output_bytes`` acotado y un ``capture_lines`` acotado. Todas las
    operaciones construyen argv internamente; el caller nunca aporta argv.
    """

    def __init__(self, tmux_path, git_path, python_path, worktree,
                 timeout_seconds, max_output_bytes, capture_lines):
        self._tmux = _require_absolute_executable(tmux_path, "tmux_path")
        self._git = _require_absolute_executable(git_path, "git_path")
        self._python = _require_absolute_executable(python_path, "python_path")
        try:
            validate_worktree_path(worktree)
        except HostObserverError as error:
            raise ReviewRunnerError(
                "worktree debe ser absoluto, normalizado y distinto de raíz"
            ) from error
        self._worktree = worktree
        if (not isinstance(timeout_seconds, (int, float))
                or isinstance(timeout_seconds, bool)
                or not math.isfinite(timeout_seconds)
                or not (_TIMEOUT_FLOOR < timeout_seconds <= _TIMEOUT_CEILING)):
            raise ReviewRunnerError(
                f"timeout_seconds debe ser un número finito en (0, {_TIMEOUT_CEILING:g}]"
            )
        if (not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool)
                or not (0 < max_output_bytes <= _MAX_OUTPUT_CEILING)):
            raise ReviewRunnerError("max_output_bytes debe ser un entero acotado positivo")
        if (not isinstance(capture_lines, int) or isinstance(capture_lines, bool)
                or not (_CAPTURE_LINES_FLOOR <= capture_lines <= _CAPTURE_LINES_CEILING)):
            raise ReviewRunnerError(
                f"capture_lines debe ser un entero en "
                f"[{_CAPTURE_LINES_FLOOR}, {_CAPTURE_LINES_CEILING}]"
            )
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes
        self._capture_lines = capture_lines
        # Entorno de unit_tests por instancia: PYTHONPATH liga este worktree/src
        # (no el checkout principal); PYTHONNOUSERSITE evita user-site hostil.
        self._unit_test_env = dict(_UNIT_TEST_ENV_BASE)
        self._unit_test_env["PYTHONPATH"] = worktree + "/src"
        self._unit_test_env["PYTHONNOUSERSITE"] = "1"

    # -- subprocess de bajo nivel ----------------------------------------

    def _run(self, argv, cwd, env):
        """Ejecuta argv cerrado (shell=False, stdin DEVNULL, env inyectado).

        Devuelve el ``CompletedProcess``-like ``(stdout, stderr, returncode)``.
        Falla cerrado ante timeout u OSError (executable ausente/inaccesible) y
        overflow de salida combinada (antes de interpretar exit). Los mensajes
        de error no incluyen stdout/stderr.
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
                env=env,
            )
        except subprocess.TimeoutExpired as error:
            raise IndeterminateReviewError("timeout agotado") from error
        except OSError as error:
            raise IndeterminateReviewError("executable ausente o inaccesible") from error
        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        # Overflow ANTES de interpretar exit; no inspeccionamos contenido.
        if len(stdout) + len(stderr) > self._max_output:
            raise IndeterminateReviewError("salida combinada sobre el límite")
        return stdout, stderr, completed.returncode

    @staticmethod
    def _strict(stdout, stderr, returncode, what):
        """Exige exit 0 y stderr vacío (observación read-only estricta)."""
        if returncode != 0:
            raise IndeterminateReviewError(f"{what} exit no cero")
        if stderr:
            raise IndeterminateReviewError(f"{what} stderr no vacío")
        return _decode_utf8(stdout, what)

    # -- captura acotada -------------------------------------------------

    def capture_once(self, session_name):
        """Una única captura ``capture-pane`` acotada; devuelve metadata sólo."""
        try:
            session = validate_session_name(session_name)
        except HostObserverError as error:
            raise ReviewRunnerError(
                "session_name debe ser un identificador cerrado"
            ) from error
        # ``-J`` une líneas envueltas (join explícito). ``-p`` imprime a stdout.
        # ``-S -{N}`` acota el scrollback; el final es el bottom del pane.
        argv = [
            self._tmux, "capture-pane", "-t", session, "-p", "-J",
            "-S", f"-{self._capture_lines}",
        ]
        stdout, stderr, returncode = self._run(argv, None, _CAPTURE_ENV)
        text = self._strict(stdout, stderr, returncode, "capture_once")
        return CaptureOutcome(
            digest=_digest(text),
            length_utf8=_length(text),
            capture_lines=self._capture_lines,
        )

    # -- checks cerrados -------------------------------------------------

    def run_check(self, check_id):
        if not isinstance(check_id, str) or check_id not in _CHECK_CATALOG:
            raise ReviewRunnerError(f"check_id no está en el catálogo: {check_id!r}")
        if check_id == "git_status":
            return self._git_status()
        if check_id == "diff_check":
            return self._diff_check()
        return self._unit_tests()

    def _git_status(self):
        argv = [
            self._git, "-c", "core.fsmonitor=false",
            "status", "--porcelain=v1", "--untracked-files=normal", "--",
        ]
        stdout, stderr, returncode = self._run(argv, self._worktree, _GIT_CHECK_ENV)
        # Observación read-only estricta: exit 0, stderr vacío.
        text = self._strict(stdout, stderr, returncode, "git_status")
        # git_status siempre pass (exit 0): es evidencia, no gate.
        return CheckOutcome("git_status", "pass", _digest(text), _length(text))

    def _diff_check(self):
        # Cubre staged + unstado vs HEAD en una sola llamada read-only;
        # --no-ext-diff excluye external diff; -- termina opciones/revisiones.
        argv = [
            self._git, "-c", "core.fsmonitor=false",
            "diff", "--no-ext-diff", "--check", "HEAD", "--",
        ]
        stdout, stderr, returncode = self._run(argv, self._worktree, _GIT_CHECK_ENV)
        # exit 0 = pass (sin errores de whitespace), exit 1 = fail (errores).
        if returncode == 0:
            status = "pass"
        elif returncode == 1:
            status = "fail"
        else:
            raise IndeterminateReviewError("diff_check exit inesperado")
        if stderr:
            raise IndeterminateReviewError("diff_check stderr no vacío")
        text = _decode_utf8(stdout, "diff_check")
        return CheckOutcome("diff_check", status, _digest(text), _length(text))

    def _unit_tests(self):
        argv = [
            self._python, "-m", "unittest", "discover",
            "-s", "tests", "-p", "test_*.py",
        ]
        stdout, stderr, returncode = self._run(argv, self._worktree, self._unit_test_env)
        # unit_tests escribe a stderr (output de tests); exit 0 = pass.
        status = "pass" if returncode == 0 else "fail"
        combined = stdout + stderr
        text = _decode_utf8(combined, "unit_tests")
        return CheckOutcome("unit_tests", status, _digest(text), _length(text))
