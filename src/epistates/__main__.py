"""CLI para validar contratos y descubrir la superficie de Epistates.

Carácter estático vs. I/O:

- ``--version``, ``--help`` y ``describe --format json`` son estáticos: no
  ejecutan subprocess, no abren sockets, no leen el reloj ni sondean el host.
- ``validate`` hace I/O de filesystem (lee archivos JSON del disco) pero no
  inicia adaptadores ni resuelve checks. La validez de un artefacto no
  constituye autorización.

Superficie:

- ``epistates --version``: versión single-source del paquete (exit 0).
- ``epistates validate <artifact> [--binding ...] [--format text|json]``:
  valida artefacto + binding. En ``--format json`` emite exactamente un objeto
  ``epistates/validation-report/v1`` ASCII-escapado, determinista, con
  ``stderr`` vacío y taxonomía de errores cerrada; en ``--format text``
  (default) conserva las cadenas ``VALID``/``INVALID`` compatibles.
- ``epistates describe --format json``: documento estático
  ``epistates/discovery/v1`` (un único JSON determinista en stdout, stderr
  vacío, ASCII-escapado y robusto ante locale/encoding).

Códigos de salida (Slice2):

- ``0``: contrato y binding válidos.
- ``1``: entrada/JSON/contrato/binding inválido.
- ``2``: uso CLI incorrecto.

En ``--format json`` todo error posterior a reconocer el modo machine produce
un único JSON en stdout y ``stderr`` vacío. La única excepción documentada es
un uso argparse incorrecto que argparse rechaza antes de reconocer
``--format json`` (p. ej. ``--format yaml``): ahí el error va a ``stderr`` en
modo texto y termina ``2``.

No existe CLI operativo para observe/dispatch/review/audit: esas operaciones
requieren autoridad externa y runners inyectados, y quedan fuera del alcance
estático de descubrimiento.
"""

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ._version import __version__
from .adapter import validate_adapter_capabilities
from .audit import validate_audit_binding, validate_audit_result
from .audit_review import validate_audit_review_binding
from .contracts import ValidationError, validate_task_card
from .dispatch import _MESSAGE_MAX_BYTES, validate_dispatch_receipt, validate_dispatch_receipt_binding
from .discovery import render_discovery_json
from .human_notice import validate_human_notice, validate_human_notice_binding
from .preflight import validate_preflight_binding, validate_preflight_result
from .review import validate_review_evidence, validate_review_evidence_binding


# ---------------------------------------------------------------------------
# Schema del reporte machine-readable publicado por este corte.
# ---------------------------------------------------------------------------

_REPORT_SCHEMA = "epistates/validation-report/v1"
_REPORT_VERSION = "v1"

# Límite de bytes por artefacto JSON leído por validate (1 MiB). Mensajes van
# por su propio límite (_MESSAGE_MAX_BYTES).
_ARTIFACT_MAX_BYTES = 1 * 1024 * 1024
# Profundidad JSON máxima imposta explícitamente después del parse.
_MAX_JSON_DEPTH = 100


_VALIDATORS = {
    "epistates/task-card/v1": validate_task_card,
    "epistates/audit-result/v1": validate_audit_result,
    "epistates/adapter-capabilities/v1": validate_adapter_capabilities,
    "epistates/preflight-result/v1": validate_preflight_result,
    "epistates/dispatch-receipt/v1": validate_dispatch_receipt,
    "epistates/human-notice/v1": validate_human_notice,
    "epistates/review-evidence/v1": validate_review_evidence,
}

# Opciones de binding de la cadena de revisión (compartidas por dispatch-receipt,
# human-notice y review-evidence). El audit-result en modo puente las exige todas.
_REVIEW_BINDING_OPTIONS = (
    "task_card", "adapter_capabilities", "run_id", "attempt_id",
    "expected_session_name", "expected_command", "message_file",
    "preflight_result", "max_preflight_age_seconds",
    "dispatch_receipt", "human_notice", "max_dispatch_age_seconds",
    "max_notice_age_seconds",
)
# Opciones de decisión de auditoría propias del puente review-evidence ->
# audit-result (Slice5). Sólo aplican al audit-result en modo puente.
_AUDIT_DECISION_OPTIONS = (
    "review_evidence", "expected_classification", "expected_decision",
    "expected_decision_reference", "expected_observed_at",
    "max_audit_age_seconds", "expected_grant_id", "expected_grant_digest",
)
# Todas las opciones de binding reconocidas por el CLI.
_ALL_BINDING_OPTIONS = _REVIEW_BINDING_OPTIONS + _AUDIT_DECISION_OPTIONS

# Opciones aplicables (y requeridas) por schema de binding.
_APPLICABLE = {
    "epistates/task-card/v1": frozenset(),
    "epistates/adapter-capabilities/v1": frozenset(),
    "epistates/audit-result/v1": frozenset({"task_card", "run_id", "attempt_id"}),
    "epistates/preflight-result/v1": frozenset({
        "task_card", "adapter_capabilities", "run_id", "attempt_id",
        "expected_session_name", "expected_command",
    }),
    "epistates/dispatch-receipt/v1": frozenset({
        "task_card", "adapter_capabilities", "preflight_result", "run_id",
        "attempt_id", "expected_session_name", "expected_command",
        "max_preflight_age_seconds", "message_file",
    }),
    "epistates/human-notice/v1": frozenset({
        "task_card", "adapter_capabilities", "dispatch_receipt", "run_id",
        "attempt_id", "expected_session_name", "max_dispatch_age_seconds",
    }),
    "epistates/review-evidence/v1": frozenset(_REVIEW_BINDING_OPTIONS),
}


# ---------------------------------------------------------------------------
# Errores clasificados para el reporte machine-readable.
# ---------------------------------------------------------------------------


class ValidateError(Exception):
    """Base de errores clasificados para el reporte machine-readable.

    Cada instancia declara la ``phase`` (``load``/``contract``/``binding``) que
    falló, un ``code`` estable de la taxonomía cerrada, el ``message`` saneado,
    el ``artifact_schema`` conocido hasta el fallo (o ``None``) y ``details``
    estructurados. ``completed_phases`` registra las fases anteriores que sí
    pasaron, para que el reporte las marque como ``valid``.
    """

    __slots__ = (
        "phase", "code", "message", "artifact_schema", "details",
        "completed_phases",
    )

    def __init__(
        self, phase: str, code: str, message: str,
        *,
        artifact_schema: Optional[str] = None,
        details: Optional[Mapping[str, Any]] = None,
        completed_phases: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        self.message = message
        self.artifact_schema = artifact_schema
        self.details = dict(details) if details else {}
        self.completed_phases = list(completed_phases or [])


class HardenedFileError(ValueError):
    """Error de carga endurecida con código estable + ruta origen.

    Se lanza desde el loader seguro (``_safe_read_regular_file`` y
    ``_safe_load_json_file``); la fase de validación que lo invoque lo
    reclasifica en ``ValidateError`` conservando ``code``/``details``.
    """

    def __init__(
        self, code: str, message: str, path: str,
        *, details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.details = dict(details) if details else {}


# ---------------------------------------------------------------------------
# Detección de modo machine (pre-scan de argv).
# ---------------------------------------------------------------------------
#
# ``argparse`` procesa argv de izquierda a derecha. Cuando reconoce un uso
# incorrecto llama a ``parser.error()`` que por defecto imprime a stderr y
# llama a ``sys.exit(2)``. En modo machine queremos que ese mismo camino emita
# el reporte JSON a stdout y mantenga ``stderr`` vacío.
#
# Para decidir el modo antes de cualquier parse, hacemos un pre-scan simple de
# argv buscando ``--format json`` o ``--format=json`` como valor del
# subcomando ``validate``. Esto cubre tanto errores de argparse como errores
# posteriores (carga, contrato, binding).

_MACHINE_MODE = False


def _set_machine_mode(enabled: bool) -> None:
    global _MACHINE_MODE
    _MACHINE_MODE = bool(enabled)


def _machine_mode_enabled() -> bool:
    return _MACHINE_MODE


def _argv_has_format_json(argv: Sequence[str]) -> bool:
    """Refleja la semántica last-wins de argparse para ``--format``.

    Una aparición final sin valor conserva la última selección completa: el
    error de uso ocurrió después de que esa selección ya fue reconocida.
    """
    selected: Optional[str] = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--format":
            # Un token que empieza por '-' es otra opción, no un valor
            # completo de --format. Argparse lo rechazará por uso, pero el
            # canal conserva la última selección completa reconocida.
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                selected = argv[i + 1]
                i += 2
                continue
            i += 1
            continue
        if token.startswith("--format="):
            selected = token.split("=", 1)[1]
        i += 1
    return selected == "json"


def _detect_machine_mode(argv: Optional[Sequence[str]]) -> bool:
    """True iff argv corresponde a ``validate ... --format json``.

    Exige que el primer token no-opción sea ``validate``: el modo machine es
    exclusivo del subcomando ``validate``. ``describe --format json`` sigue
    emitiendo ``epistates/discovery/v1`` (no es reporte de validación).
    """
    if argv is None:
        argv = sys.argv[1:]
    subcommand: Optional[str] = None
    for token in argv:
        if not isinstance(token, str):
            return False
        if token.startswith("-"):
            continue
        subcommand = token
        break
    if subcommand != "validate":
        return False
    return _argv_has_format_json(argv)


# ---------------------------------------------------------------------------
# Helpers de binding y números.
# ---------------------------------------------------------------------------


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"clave JSON duplicada: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    """Rechaza NaN/Infinity/-Infinity: no son valores JSON canónicos."""
    raise ValueError(f"constante JSON no soportada: {value}")


def _provided_binding_options(args) -> set:
    """Conjunto de opciones de binding presentes en ``args``."""
    return {name for name in _ALL_BINDING_OPTIONS if getattr(args, name) is not None}


def _check_applicability(schema: str, args) -> None:
    """Exige que toda opción de binding provista aplique al schema actual."""
    applicable = _APPLICABLE[schema]
    provided = _provided_binding_options(args)
    inapplicable = provided - applicable
    if inapplicable:
        rendered = ", ".join(
            "--" + name.replace("_", "-") for name in sorted(inapplicable)
        )
        if schema in ("epistates/task-card/v1", "epistates/adapter-capabilities/v1"):
            raise ValidationError(f"opciones de binding sólo aplican a audit-result, preflight-result, dispatch-receipt, human-notice o review-evidence: {rendered}")
        raise ValidationError(
            f"opciones de binding inaplicables a {schema.split('/')[1]}: {rendered}"
        )


def _require_applicable(schema: str, args) -> None:
    """Exige que toda opción aplicable al schema esté presente."""
    applicable = _APPLICABLE[schema]
    missing = applicable - _provided_binding_options(args)
    if missing:
        rendered = ", ".join(
            "--" + name.replace("_", "-") for name in sorted(missing)
        )
        raise ValidationError(f"{schema.split('/')[1]} requiere {rendered}")


def _require_audit_review_options(args) -> None:
    """Exige que toda opción de binding aplique al audit-result en modo puente.

    En modo puente todas las opciones de la cadena de revisión y de decisión de
    auditoría son aplicables y requeridas. Las opciones inaplicables no aplican
    aquí (todas lo son); el rechazo de opciones inaplicables a otros schemas se
    mantiene vía ``_check_applicability``.
    """
    applicable = frozenset(_ALL_BINDING_OPTIONS)
    provided = _provided_binding_options(args)
    inapplicable = provided - applicable
    if inapplicable:
        rendered = ", ".join(
            "--" + name.replace("_", "-") for name in sorted(inapplicable)
        )
        raise ValidationError(
            f"opciones de binding inaplicables a audit-result: {rendered}"
        )
    missing = applicable - provided
    if missing:
        rendered = ", ".join(
            "--" + name.replace("_", "-") for name in sorted(missing)
        )
        raise ValidationError(f"audit-result requiere {rendered}")


def _parse_number(value: Optional[str], name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} debe ser un número")


# ---------------------------------------------------------------------------
# Carga segura compartida: archivo regular, lectura acotada, anti-TOCTOU.
# ---------------------------------------------------------------------------
#
# Todo archivo leído por ``validate`` (artefacto, bindings y message-file) pasa
# por el mismo loader. Las garantías, todas fail-closed:
#
# - Sólo archivos regulares: se rechazan symlink (vía lstat + O_NOFOLLOW),
#   directorio, FIFO, socket y device, sin bloquear (O_NONBLOCK evita que la
#   apertura de un FIFO/socket cuelgue esperando un peer).
# - Apertura fail-closed: se valida el descriptor real con fstat.
# - Límite explícito por archivo: lectura ``limit + 1`` (stat es sólo
#   optimización/fast-path).
# - Detección de cambio ambiguo durante la lectura: se comparan identidad
#   (st_dev/st_ino) y metadata (st_size/st_mtime_ns/st_ctime_ns) antes/después
#   de leer; si difieren, se rechaza con código estable.
# - UTF-8 estricto, claves duplicadas, NaN/Infinity, JSON profundo y
#   RecursionError rechazados sin traceback.
#
# La salida machine es ensure_ascii: rutas, argv y mensajes con C0/DEL/C1/ANSI
# o Unicode hostil nunca inyectan terminal ni rompen el JSON.


def _file_kind_name(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "char_device"
    if stat.S_ISBLK(mode):
        return "block_device"
    return "unknown"


def _metadata_snapshot(st: os.stat_result) -> Dict[str, Any]:
    return {
        "st_dev": st.st_dev,
        "st_ino": st.st_ino,
        "st_size": st.st_size,
        "st_mtime_ns": st.st_mtime_ns,
        "st_ctime_ns": st.st_ctime_ns,
    }


def _metadata_differs(a: os.stat_result, b: os.stat_result) -> bool:
    return (
        a.st_dev != b.st_dev
        or a.st_ino != b.st_ino
        or a.st_size != b.st_size
        or a.st_mtime_ns != b.st_mtime_ns
        or a.st_ctime_ns != b.st_ctime_ns
    )


def _read_bounded_fd(fd: int, max_bytes: int) -> bytes:
    """Lee como mucho ``max_bytes`` desde ``fd`` sin capturar más allá."""
    chunks: List[bytes] = []
    remaining = max_bytes
    while remaining > 0:
        try:
            chunk = os.read(fd, remaining)
        except OSError as exc:
            raise HardenedFileError(
                "read_failed", f"fallo de lectura: {exc}", "",
            )
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _safe_read_regular_file(path: Path, limit: int) -> bytes:
    """Lee como mucho ``limit`` bytes de un archivo regular, fail-closed.

    Secuencia:
      1. ``lstat`` pre-check: rechaza symlink Y todo archivo no regular
         (directorio/FIFO/socket/device) antes de intentar abrir. Evita
         edge-cases como que ``os.open`` sobre un socket devuelva ENXIO.
      2. ``os.open`` con ``O_RDONLY | O_NOFOLLOW | O_NONBLOCK``: nunca sigue un
         symlink en el componente final y no bloquea en FIFO/socket.
      3. ``fstat`` del descriptor real: exige archivo regular (defensa en
         profundidad ante TOCTOU entre lstat y open).
      4. Lectura acotada a ``limit + 1`` bytes.
      5. ``fstat`` post-lectura: compara identidad y metadata. Si difieren,
         falla cerrado (``file_changed_during_read``).
      6. Si se leyeron más de ``limit`` bytes, falla cerrado (``file_too_large``).
    """
    p = str(path)

    # 1. lstat pre-check.
    try:
        lst = os.lstat(p)
    except FileNotFoundError as exc:
        raise HardenedFileError(
            "file_not_found", f"archivo no encontrado: {p}", p,
        ) from exc
    except OSError as exc:
        raise HardenedFileError(
            "open_failed", f"no se pudo acceder al archivo: {p}", p,
        ) from exc

    if stat.S_ISLNK(lst.st_mode):
        raise HardenedFileError(
            "file_is_symlink",
            f"se rechaza symlink como entrada: {p}", p,
        )
    if not stat.S_ISREG(lst.st_mode):
        kind = _file_kind_name(lst.st_mode)
        raise HardenedFileError(
            "file_not_regular",
            f"se rechaza entrada no regular ({kind}): {p}",
            p,
            details={"kind": kind},
        )

    # Fast-path: stat reporting > limit -> rechazar antes de abrir.
    if lst.st_size > limit:
        raise HardenedFileError(
            "file_too_large",
            f"archivo excede el límite de {limit} bytes",
            p,
            details={"limit_bytes": limit, "st_size": lst.st_size},
        )

    # 2. Open fail-closed.
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise HardenedFileError(
            "open_failed", f"no se pudo abrir el archivo: {p}", p,
        ) from exc

    try:
        # 3. fstat del descriptor real (defensa anti-TOCTOU lstat -> open).
        try:
            before = os.fstat(fd)
        except OSError as exc:
            raise HardenedFileError(
                "open_failed", f"fstat falló: {p}", p,
            ) from exc
        if not stat.S_ISREG(before.st_mode):
            kind = _file_kind_name(before.st_mode)
            raise HardenedFileError(
                "file_not_regular",
                f"se rechaza entrada no regular ({kind}): {p}",
                p,
                details={"kind": kind},
            )

        # 4. Lectura acotada.
        raw = _read_bounded_fd(fd, limit + 1)

        # 5. fstat post-lectura: detectar cambio ambiguo.
        try:
            after = os.fstat(fd)
        except OSError as exc:
            raise HardenedFileError(
                "file_changed_during_read",
                f"fstat post-lectura falló: {p}", p,
            ) from exc
        if _metadata_differs(before, after):
            raise HardenedFileError(
                "file_changed_during_read",
                f"el archivo cambió durante la lectura: {p}",
                p,
                details={
                    "before": _metadata_snapshot(before),
                    "after": _metadata_snapshot(after),
                },
            )
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    # 6. Tamaño real leído.
    if len(raw) > limit:
        raise HardenedFileError(
            "file_too_large",
            f"archivo excede el límite de {limit} bytes",
            p,
            details={"limit_bytes": limit, "read_bytes": len(raw)},
        )

    return raw


def _safe_load_json_file(path: Path, limit: int = _ARTIFACT_MAX_BYTES) -> Any:
    """Carga JSON desde disco vía ``_safe_read_regular_file`` + parser seguro."""
    p = str(path)
    raw = _safe_read_regular_file(path, limit)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HardenedFileError(
            "invalid_utf8",
            f"UTF-8 inválido en {p}: {exc}",
            p,
            details={"reason": str(exc)},
        ) from exc

    return _parse_json_safe(text, p)


def _parse_json_safe(text: str, source_path: str) -> Any:
    """Parser JSON con claves duplicadas, NaN/Infinity, profundidad y RecursionError."""
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise HardenedFileError(
            "invalid_json",
            f"JSON inválido en {source_path}: {exc}",
            source_path,
            details={"line": exc.lineno, "column": exc.colno, "position": exc.pos},
        ) from exc
    except ValueError as exc:
        msg = str(exc)
        if "duplicada" in msg:
            raise HardenedFileError(
                "duplicate_json_key", msg, source_path,
            ) from exc
        if "constante JSON no soportada" in msg:
            raise HardenedFileError(
                "json_unsupported_constant", msg, source_path,
            ) from exc
        raise HardenedFileError(
            "invalid_json", f"JSON inválido en {source_path}: {msg}", source_path,
        ) from exc
    except RecursionError as exc:
        raise HardenedFileError(
            "recursion_error",
            f"RecursionError parseando {source_path}: JSON demasiado profundo",
            source_path,
        ) from exc

    depth = _measure_depth(parsed)
    if depth > _MAX_JSON_DEPTH:
        raise HardenedFileError(
            "json_too_deep",
            (
                f"JSON excede profundidad máxima {_MAX_JSON_DEPTH} "
                f"en {source_path}"
            ),
            source_path,
            details={"max_depth": _MAX_JSON_DEPTH, "measured_depth": depth},
        )
    return parsed


def _measure_depth(node: Any) -> int:
    """Profundidad máxima anidada; iterativa con tope para no colgar."""
    if not isinstance(node, (dict, list)):
        return 0
    max_seen = 0
    stack: List[Tuple[Any, int]] = [(node, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > max_seen:
            max_seen = depth
            if max_seen > _MAX_JSON_DEPTH:
                return max_seen
        if isinstance(item, dict):
            for value in item.values():
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
        else:  # list
            for value in item:
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
    return max_seen


def _safe_read_message_file(path: Path, limit: int = _MESSAGE_MAX_BYTES) -> bytes:
    """Lee el message-file por la misma ruta segura (archivo regular acotado).

    Conserva el contrato del ``message-file`` previo: lectura acotada a
    ``limit`` bytes, anti-TOCTOU, sin seguir symlinks. El dispatcher sigue
    aplicando ``_validate_message`` sobre los bytes decodificados.
    """
    return _safe_read_regular_file(path, limit)


def _safe_load_message_text(
    path: Path, limit: int = _MESSAGE_MAX_BYTES,
) -> str:
    """Carga el mensaje como UTF-8 estricto conservando el código estable.

    El mensaje no es JSON, pero forma parte del binding y debe recibir el mismo
    tratamiento fail-closed que los artefactos auxiliares. En particular, un
    byte inválido se reporta como ``invalid_utf8`` y no se degrada al genérico
    ``binding_invalid``.
    """
    raw = _safe_read_message_file(path, limit)
    p = str(path)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HardenedFileError(
            "invalid_utf8",
            f"UTF-8 inválido en {p}: {exc}",
            p,
            details={"reason": str(exc)},
        ) from exc


def _read_bounded_message(path: Path, limit: int) -> bytes:
    """Backward-compat shim; equivalente a ``_safe_read_message_file``."""
    return _safe_read_message_file(path, limit)


# ---------------------------------------------------------------------------
# Sanitización de errores argparse: argv con cualquier Unicode Cc no contamina.
# ---------------------------------------------------------------------------

# Categoría Unicode Cc completa: C0 (U+0000–U+001F), DEL (U+007F) y C1
# (U+0080–U+009F), incluidos NEL (U+0085) y CSI (U+009B).
_CONTROL_CHAR = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _escape_control_chars(value: str) -> str:
    """Reemplaza cualquier carácter de control (Unicode Cc) por forma visible.

    Cubre C0 (LF/CR/TAB/NUL/ESC...), DEL y C1 (U+0080–U+009F, incluidos
    U+0085/NEL y U+009B/CSI). Evita que argv hostil se refleje crudo en mensajes
    de argparse (inyección de terminal/log). ``argparse`` aplica ``repr`` a
    algunas partes (p. ej. ``invalid choice``) pero no a todas (p. ej.
    ``unrecognized arguments`` hace un join crudo); esta función cubre ambos.
    """
    def _replace(match: "re.Match[str]") -> str:
        return repr(match.group())[1:-1]

    return _CONTROL_CHAR.sub(_replace, value)


def _safe_for_json_string(value: Any) -> Optional[str]:
    """Convierte ``value`` a string saneado para uso como campo JSON.

    Descarta cualquier cosa que no sea ``str``/``Path`` (no inferimos): el
    reporte prefiere ``null`` a un valor fabricado.
    """
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value
    return None


class _SafeArgumentParser(argparse.ArgumentParser):
    """Parser que sanea argv reflejado en errores; JSON en modo machine."""

    def error(self, message: str):  # type: ignore[override]
        sanitized = _escape_control_chars(message)
        if _machine_mode_enabled():
            report = _build_usage_error_report(sanitized)
            sys.stdout.write(render_report_json(report))
            sys.exit(2)
        super().error(sanitized)


class _FixedWidthHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Formatter determinista que nunca consulta el terminal del host."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog, width=100, max_help_position=32)


# ---------------------------------------------------------------------------
# Matriz de aplicabilidad de ``validate`` (fuente compartida con _APPLICABLE).
# ---------------------------------------------------------------------------

_SCHEMA_LABELS = {
    "epistates/task-card/v1": "task-card/v1",
    "epistates/adapter-capabilities/v1": "adapter-capabilities/v1",
    "epistates/audit-result/v1": "audit-result/v1 (H2)",
    "epistates/preflight-result/v1": "preflight-result/v1",
    "epistates/dispatch-receipt/v1": "dispatch-receipt/v1",
    "epistates/human-notice/v1": "human-notice/v1",
    "epistates/review-evidence/v1": "review-evidence/v1",
}


def _flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def _format_applicability_matrix() -> str:
    """Genera la matriz de opciones requeridas por schema para ``validate --help``."""
    lines = []
    lines.append("Opciones de binding requeridas por schema:")
    order = [
        "epistates/task-card/v1",
        "epistates/adapter-capabilities/v1",
        "epistates/audit-result/v1",
        "epistates/preflight-result/v1",
        "epistates/dispatch-receipt/v1",
        "epistates/human-notice/v1",
        "epistates/review-evidence/v1",
    ]
    for schema in order:
        applicable = _APPLICABLE.get(schema, frozenset())
        flags = " ".join(_flag(n) for n in sorted(applicable))
        label = _SCHEMA_LABELS[schema]
        lines.append(f"  {label:<32}: {flags or '(sin opciones de binding)'}")
    lines.append("")
    lines.append(
        "audit-result/v1 en modo bridge (campo 'review_evidence_digest' "
        "presente) requiere el conjunto COMPLETO de opciones de binding:"
    )
    # Set explícito y completo: cadena de revisión + decisión/autoridad.
    bridge_all = list(_REVIEW_BINDING_OPTIONS) + list(_AUDIT_DECISION_OPTIONS)
    lines.append("  " + " ".join(_flag(n) for n in bridge_all))
    lines.append("")
    lines.append(
        "Toda opcion de binding inaplicable al schema se rechaza (no se "
        "ignora). Un valor invalido termina exit 1; un uso incorrecto exit 2."
    )
    lines.append("")
    lines.append(
        "--format text (default) emite 'VALID: <path>'/'INVALID: <msg>'; "
        "--format json emite un unico objeto epistates/validation-report/v1 "
        "ASCII-escapado con taxonomia de errores cerrada y exit codes 0/1/2."
    )
    return "\n".join(lines)


def _build_parser() -> "_SafeArgumentParser":
    """Construye el parser con ayuda, --version, validate y describe.

    Usa ``_SafeArgumentParser`` (sanitiza argv en errores) y ``parser_class``
    para que los subparsers hereden el mismo comportamiento.
    ``allow_abbrev=False`` garantiza que el pre-scan de modo machine coincida
    exactamente con el parseo (``--form`` no se expande a ``--format``).
    """
    parser = _SafeArgumentParser(
        prog="epistates",
        allow_abbrev=False,
        description=(
            "Epistates: supervisor contractual de agentes externos.\n"
            "Caracter: --version/--help/describe son estaticos (no sondean el "
            "host); validate hace I/O de filesystem pero no inicia adaptadores.\n"
            "La validez de un artefacto no es autorizacion; el descubrimiento "
            "no concluye disponibilidad, vigencia o autorizacion."
        ),
        epilog=(
            "Frontera de confianza: descrito != implementado != observado != "
            "autorizado. Use 'describe --format json' para la superficie "
            "instalada y 'validate' para validar contratos."
        ),
        formatter_class=_FixedWidthHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
        help="Imprime la version single-source del paquete y termina (exit 0).",
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=_SafeArgumentParser,
    )

    validate = subparsers.add_parser(
        "validate",
        allow_abbrev=False,
        help="validar un artefacto sin ejecutar checks ni iniciar adaptadores",
        description=(
            "Valida un artefacto y, segun el schema, su binding completo, sin "
            "resolver checks ni iniciar procesos externos. Hace I/O de "
            "filesystem al leer los archivos. La validez no constituye "
            "autorizacion."
        ),
        epilog=_format_applicability_matrix(),
        formatter_class=_FixedWidthHelpFormatter,
    )
    validate.add_argument(
        "card", type=Path, metavar="artifact",
        help="Artefacto a validar (JSON con campo 'schema'); se lee de disco.",
    )
    validate.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help=(
            "Formato de salida. 'text' (default): salida VALID/INVALID "
            "compatible. 'json': un unico objeto epistates/validation-report/v1 "
            "ASCII-escapado, determinista, con taxonomia de errores cerrada y "
            "exits 0/1/2. En modo json, todo error posterior a reconocer el "
            "modo emite JSON unico por stdout con stderr vacio."
        ),
    )
    validate.add_argument(
        "--task-card", type=Path,
        help="Path a la tarjeta task-card/v1 para binding (JSON).",
    )
    validate.add_argument(
        "--adapter-capabilities", type=Path,
        help="Path a adapter-capabilities/v1 para binding (JSON).",
    )
    validate.add_argument(
        "--run-id",
        help="Run id esperado para binding (catalogo [a-z][a-z0-9-]{2,63}).",
    )
    validate.add_argument(
        "--attempt-id",
        help="Attempt id esperado para binding (catalogo [a-z][a-z0-9-]{2,63}).",
    )
    validate.add_argument(
        "--expected-session-name",
        help="Nombre de sesion tmux esperado (identificador cerrado).",
    )
    validate.add_argument(
        "--expected-command",
        help="Comando esperado en el pane observado (p. ej. 'idle').",
    )
    validate.add_argument(
        "--message-file", type=Path,
        help="Path al mensaje literal entregado (UTF-8 crudo, lectura acotada).",
    )
    validate.add_argument(
        "--preflight-result", type=Path,
        help="Path a preflight-result/v1 para binding (JSON).",
    )
    validate.add_argument(
        "--max-preflight-age-seconds",
        help="Politica externa de frescura preflight->dispatch en segundos (0,3600].",
    )
    validate.add_argument(
        "--dispatch-receipt", type=Path,
        help="Path a dispatch-receipt/v1 para binding (JSON).",
    )
    validate.add_argument(
        "--human-notice", type=Path,
        help="Path a human-notice/v1 para binding (JSON).",
    )
    validate.add_argument(
        "--max-dispatch-age-seconds",
        help="Politica externa de frescura dispatch->notice en segundos (0,7200].",
    )
    validate.add_argument(
        "--max-notice-age-seconds",
        help="Politica externa de frescura notice->review en segundos (0,7200].",
    )
    validate.add_argument(
        "--review-evidence", type=Path,
        help="Path a review-evidence/v1 para binding (JSON; audit bridge).",
    )
    validate.add_argument(
        "--expected-classification",
        help="Clasificacion inyectada esperada (audit bridge): OK|PARCIAL|BLOQ.",
    )
    validate.add_argument(
        "--expected-decision",
        help="Decision inyectada esperada (audit bridge): proceed|fix-and-retry|escalate.",
    )
    validate.add_argument(
        "--expected-decision-reference",
        help="Referencia de decision externa inyectada (audit bridge).",
    )
    validate.add_argument(
        "--expected-observed-at",
        help="Timestamp observado esperado inyectado (audit bridge; RFC3339 UTC Z).",
    )
    validate.add_argument(
        "--max-audit-age-seconds",
        help="Politica externa de frescura review->audit en segundos (0,7200].",
    )
    validate.add_argument(
        "--expected-grant-id",
        help=("Grant id inyectado por el control-plane externo (audit bridge); "
              "la coincidencia con la tarjeta solo liga correlacion."),
    )
    validate.add_argument(
        "--expected-grant-digest",
        help=("Grant digest inyectado por el control-plane externo (audit bridge); "
              "ligarlo al authority de la tarjeta NO autentica el grant."),
    )

    describe = subparsers.add_parser(
        "describe",
        allow_abbrev=False,
        help="emitir el documento de descubrimiento estatico (epistates/discovery/v1)",
        description=(
            "Emite exactamente un documento JSON con schema "
            "epistates/discovery/v1. Estatico, offline y determinista: no "
            "sondea el host, ASCII-escapado y estable ante locale/encoding."
        ),
        formatter_class=_FixedWidthHelpFormatter,
    )
    describe.add_argument(
        "--format",
        choices=["json"],
        required=True,
        help="Formato de salida. En este corte solo se soporta 'json'.",
    )
    return parser


# ---------------------------------------------------------------------------
# Ejecución por fases (load -> contract -> binding).
# ---------------------------------------------------------------------------


def _classify_binding_policy_error(exc: ValidationError) -> Tuple[str, str]:
    """Mapea el mensaje de política de binding a (code, schema_label).

    ``... requiere ...`` indica opción requerida ausente -> ``binding_missing``;
    cualquier otra política (opción inaplicable) -> ``binding_invalid``.
    """
    message = str(exc)
    if " requiere " in message:
        return "binding_missing", message
    return "binding_invalid", message


def _dispatch_binding(
    schema: str, artifact: Mapping[str, Any],
    audit_review_mode: bool, args,
) -> None:
    """Carga los archivos de binding y llama al validador de binding del schema.

    Todos los archivos pasan por ``_safe_load_json_file`` /
    ``_safe_read_message_file`` (endurecimiento compartido). Los errores se
    levantan como ``HardenedFileError`` (código estable) o como excepciones de
    los validadores; la fase que llama reclasifica.
    """
    if schema == "epistates/audit-result/v1":
        task_card = _safe_load_json_file(args.task_card)
        if audit_review_mode:
            adapter = _safe_load_json_file(args.adapter_capabilities)
            preflight_result = _safe_load_json_file(args.preflight_result)
            dispatch_receipt = _safe_load_json_file(args.dispatch_receipt)
            human_notice = _safe_load_json_file(args.human_notice)
            review_evidence = _safe_load_json_file(args.review_evidence)
            expected_max_preflight = _parse_number(
                args.max_preflight_age_seconds, "--max-preflight-age-seconds"
            )
            expected_max_dispatch = _parse_number(
                args.max_dispatch_age_seconds, "--max-dispatch-age-seconds"
            )
            expected_max_notice = _parse_number(
                args.max_notice_age_seconds, "--max-notice-age-seconds"
            )
            message = _safe_load_message_text(
                args.message_file, _MESSAGE_MAX_BYTES
            )
            expected_max_audit = _parse_number(
                args.max_audit_age_seconds, "--max-audit-age-seconds"
            )
            validate_audit_review_binding(
                artifact, review_evidence, task_card, adapter,
                preflight_result, dispatch_receipt, human_notice,
                args.run_id, args.attempt_id,
                args.expected_session_name, args.expected_command,
                expected_max_preflight, message,
                expected_max_dispatch, expected_max_notice,
                args.expected_classification, args.expected_decision,
                args.expected_decision_reference,
                args.expected_observed_at, expected_max_audit,
                args.expected_grant_id, args.expected_grant_digest,
            )
        else:
            validate_audit_binding(artifact, task_card, args.run_id, args.attempt_id)
    elif schema == "epistates/preflight-result/v1":
        task_card = _safe_load_json_file(args.task_card)
        adapter = _safe_load_json_file(args.adapter_capabilities)
        validate_preflight_binding(
            artifact, task_card, adapter, args.run_id, args.attempt_id,
            args.expected_session_name, args.expected_command,
        )
    elif schema == "epistates/dispatch-receipt/v1":
        task_card = _safe_load_json_file(args.task_card)
        adapter = _safe_load_json_file(args.adapter_capabilities)
        preflight_result = _safe_load_json_file(args.preflight_result)
        expected_max_age = _parse_number(
            args.max_preflight_age_seconds, "--max-preflight-age-seconds"
        )
        message = _safe_load_message_text(
            args.message_file, _MESSAGE_MAX_BYTES
        )
        validate_dispatch_receipt_binding(
            artifact, task_card, adapter, preflight_result,
            args.run_id, args.attempt_id,
            args.expected_session_name, args.expected_command,
            expected_max_age, message,
        )
    elif schema == "epistates/human-notice/v1":
        task_card = _safe_load_json_file(args.task_card)
        adapter = _safe_load_json_file(args.adapter_capabilities)
        dispatch_receipt = _safe_load_json_file(args.dispatch_receipt)
        expected_max_dispatch = _parse_number(
            args.max_dispatch_age_seconds, "--max-dispatch-age-seconds"
        )
        validate_human_notice_binding(
            artifact, task_card, adapter, dispatch_receipt,
            args.run_id, args.attempt_id,
            args.expected_session_name, expected_max_dispatch,
        )
    elif schema == "epistates/review-evidence/v1":
        task_card = _safe_load_json_file(args.task_card)
        adapter = _safe_load_json_file(args.adapter_capabilities)
        preflight_result = _safe_load_json_file(args.preflight_result)
        dispatch_receipt = _safe_load_json_file(args.dispatch_receipt)
        human_notice = _safe_load_json_file(args.human_notice)
        expected_max_preflight = _parse_number(
            args.max_preflight_age_seconds, "--max-preflight-age-seconds"
        )
        expected_max_dispatch = _parse_number(
            args.max_dispatch_age_seconds, "--max-dispatch-age-seconds"
        )
        expected_max_notice = _parse_number(
            args.max_notice_age_seconds, "--max-notice-age-seconds"
        )
        message = _safe_load_message_text(
            args.message_file, _MESSAGE_MAX_BYTES
        )
        validate_review_evidence_binding(
            artifact, task_card, adapter, preflight_result,
            dispatch_receipt, human_notice,
            args.run_id, args.attempt_id,
            args.expected_session_name, args.expected_command,
            expected_max_preflight, message,
            expected_max_dispatch, expected_max_notice,
        )


def _validate_phases(args) -> Tuple[Optional[str], str]:
    """Ejecuta load -> contract -> binding y devuelve (schema, binding_status).

    Raises ``ValidateError`` clasificado por fase en cualquier fallo.
    ``binding_status`` es ``not_requested``/``valid`` sólo en éxito.
    """
    # Phase: load.
    try:
        artifact = _safe_load_json_file(args.card, _ARTIFACT_MAX_BYTES)
    except HardenedFileError as exc:
        raise ValidateError(
            "load", exc.code, exc.message,
            artifact_schema=None,
            details=dict(exc.details),
        ) from exc

    if not isinstance(artifact, Mapping):
        raise ValidateError(
            "load", "schema_missing",
            "el artefacto no es un objeto JSON",
        )

    schema_value = artifact.get("schema")
    schema_str = schema_value if isinstance(schema_value, str) else None
    if schema_str not in _VALIDATORS:
        if schema_str is None:
            raise ValidateError(
                "load", "schema_missing",
                "schema ausente o no es texto",
                artifact_schema=None,
            )
        raise ValidateError(
            "load", "schema_unsupported",
            f"schema no soportado: {schema_str}",
            artifact_schema=schema_str,
        )

    # Phase: contract.
    try:
        _VALIDATORS[schema_str](artifact)
    except ValidationError as exc:
        raise ValidateError(
            "contract", "contract_violation", str(exc),
            artifact_schema=schema_str,
            completed_phases=["load"],
        ) from exc

    # Phase: binding.
    audit_review_mode = (
        schema_str == "epistates/audit-result/v1"
        and "review_evidence_digest" in artifact
    )

    try:
        if audit_review_mode:
            _require_audit_review_options(args)
        else:
            _check_applicability(schema_str, args)
            applicable = _APPLICABLE.get(schema_str, frozenset())
            if applicable:
                _require_applicable(schema_str, args)
    except ValidationError as exc:
        code, message = _classify_binding_policy_error(exc)
        raise ValidateError(
            "binding", code, message,
            artifact_schema=schema_str,
            completed_phases=["load", "contract"],
        ) from exc

    needs_binding = audit_review_mode or bool(_APPLICABLE.get(schema_str, frozenset()))
    if not needs_binding:
        return schema_str, "not_requested"

    try:
        _dispatch_binding(schema_str, artifact, audit_review_mode, args)
    except HardenedFileError as exc:
        details = dict(exc.details)
        if exc.path:
            details["path"] = exc.path
        raise ValidateError(
            "binding", exc.code, exc.message,
            artifact_schema=schema_str,
            details=details,
            completed_phases=["load", "contract"],
        ) from exc
    except ValidationError as exc:
        code, message = _classify_binding_policy_error(exc)
        raise ValidateError(
            "binding", code, message,
            artifact_schema=schema_str,
            completed_phases=["load", "contract"],
        ) from exc
    except (ValueError, TypeError) as exc:
        raise ValidateError(
            "binding", "binding_invalid", str(exc),
            artifact_schema=schema_str,
            completed_phases=["load", "contract"],
        ) from exc

    return schema_str, "valid"


# ---------------------------------------------------------------------------
# Reporte machine-readable ``epistates/validation-report/v1``.
# ---------------------------------------------------------------------------


def _empty_phases() -> Dict[str, Dict[str, Any]]:
    return {
        "load": {"status": "skipped", "error": None},
        "contract": {"status": "skipped", "error": None},
        "binding": {"status": "skipped", "error": None},
    }


def _error_obj(error: ValidateError) -> Dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "details": dict(error.details) if error.details else {},
    }


def _build_success_report(
    args, schema: Optional[str], binding_status: str,
) -> Dict[str, Any]:
    phases = _empty_phases()
    phases["load"]["status"] = "valid"
    phases["contract"]["status"] = "valid"
    phases["binding"]["status"] = binding_status
    return {
        "schema": _REPORT_SCHEMA,
        "validation_report_version": _REPORT_VERSION,
        "package_version": __version__,
        "artifact_path": _safe_for_json_string(getattr(args, "card", None)),
        "artifact_schema": schema,
        "provenance_verified": False,
        "authority_status": "external_unverified",
        "authorized_to_execute": False,
        "result": "valid",
        "exit_code": 0,
        "error": None,
        "phases": phases,
    }


def _build_failure_report(args, error: ValidateError) -> Dict[str, Any]:
    phases = _empty_phases()
    for completed in error.completed_phases:
        if completed in phases:
            phases[completed]["status"] = "valid"
    phases[error.phase]["status"] = "invalid"
    phases[error.phase]["error"] = _error_obj(error)
    artifact_path = _safe_for_json_string(getattr(args, "card", None))
    return {
        "schema": _REPORT_SCHEMA,
        "validation_report_version": _REPORT_VERSION,
        "package_version": __version__,
        "artifact_path": artifact_path,
        "artifact_schema": error.artifact_schema,
        "provenance_verified": False,
        "authority_status": "external_unverified",
        "authorized_to_execute": False,
        "result": "invalid",
        "exit_code": 1,
        "error": _error_obj(error),
        "phases": phases,
    }


def _build_usage_error_report(message: str) -> Dict[str, Any]:
    return {
        "schema": _REPORT_SCHEMA,
        "validation_report_version": _REPORT_VERSION,
        "package_version": __version__,
        "artifact_path": None,
        "artifact_schema": None,
        "provenance_verified": False,
        "authority_status": "external_unverified",
        "authorized_to_execute": False,
        "result": "invalid",
        "exit_code": 2,
        "error": {
            "code": "cli_usage_error",
            "message": message,
            "details": {},
        },
        "phases": _empty_phases(),
    }


def build_validation_report_dict(
    args, schema: Optional[str], binding_status: str,
    error: Optional[ValidateError],
) -> Dict[str, Any]:
    """Construye el dict del reporte (público para tests/discovery)."""
    if error is not None:
        return _build_failure_report(args, error)
    return _build_success_report(args, schema, binding_status)


def render_report_json(report: Mapping[str, Any]) -> str:
    """Serializa el reporte a JSON determinista, ASCII-escapado + newline."""
    return json.dumps(report, ensure_ascii=True, sort_keys=False) + "\n"


# ---------------------------------------------------------------------------
# Reporte: códigos de error publicados (taxonomía cerrada).
# ---------------------------------------------------------------------------
#
# Esta lista es la fuente canónica de la taxonomía que documenta el reporte y
# la guía de integración. Cualquier adición debe reflejarse en docs/.

_ERROR_TAXONOMY: Tuple[Tuple[str, str], ...] = (
    ("cli_usage_error", "uso CLI incorrecto detectado por argparse (exit 2)"),
    ("file_not_found", "la ruta de entrada no existe"),
    ("open_failed", "fallo de OSError al abrir/acceder al archivo"),
    ("read_failed", "fallo de OSError durante la lectura acotada"),
    ("file_is_symlink", "se rechazó symlink como entrada"),
    ("file_not_regular", "se rechazó directorio/FIFO/socket/device"),
    ("file_too_large", "el archivo excede el límite explícito de bytes"),
    ("file_changed_during_read", "identidad/metadata cambió durante la lectura"),
    ("invalid_utf8", "el contenido no es UTF-8 válido"),
    ("invalid_json", "JSON inválido (incluye trailing data y errores de parse)"),
    ("duplicate_json_key", "se rechazó clave JSON duplicada (anidada o no)"),
    ("json_unsupported_constant", "se rechazó NaN/Infinity/-Infinity"),
    ("json_too_deep", "JSON excede profundidad máxima post-parse"),
    ("recursion_error", "RecursionError durante el parseo de JSON"),
    ("schema_missing", "el artefacto no declara schema"),
    ("schema_unsupported", "schema declarado no es validable por validate"),
    ("contract_violation", "violación estructural/semántica del contrato"),
    ("binding_missing", "opción de binding requerida ausente"),
    ("binding_invalid", "binding inválido (inaplicable, archivo o validación)"),
    ("internal_error", "fallo inesperado (fail-closed genérico)"),
)


def error_taxonomy() -> Tuple[Tuple[str, str], ...]:
    """Taxonomía cerrada de ``error.code`` publicada por el reporte."""
    return tuple(_ERROR_TAXONOMY)


def report_schema() -> str:
    return _REPORT_SCHEMA


def report_version() -> str:
    return _REPORT_VERSION


def artifact_max_bytes() -> int:
    return _ARTIFACT_MAX_BYTES


def max_json_depth() -> int:
    return _MAX_JSON_DEPTH


# ---------------------------------------------------------------------------
# main().
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Pre-scan para decidir modo machine antes de construir el parser. Así los
    # errores de argparse en modo machine emiten el reporte JSON por stdout.
    _set_machine_mode(_detect_machine_mode(argv))
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "describe":
        # Estatico y determinista: stdout = unico JSON ASCII, stderr vacio.
        sys.stdout.write(render_discovery_json())
        return 0

    # validate command.
    schema: Optional[str] = None
    binding_status = "not_requested"
    error: Optional[ValidateError] = None

    try:
        schema, binding_status = _validate_phases(args)
    except ValidateError as exc:
        error = exc
    except RecursionError as exc:
        # Fail-closed genérico para recursion fuera del parser JSON.
        error = ValidateError(
            "load", "recursion_error",
            "RecursionError inesperado durante la validación",
        )
    except Exception as exc:  # pragma: no cover - fail-closed genérico.
        # Nunca filtramos traceback: emitimos un error estable.
        error = ValidateError(
            "load", "internal_error",
            "fallo inesperado durante la validación",
        )

    if args.format == "json":
        report = build_validation_report_dict(
            args, schema, binding_status, error,
        )
        sys.stdout.write(render_report_json(report))
        return report["exit_code"]

    # text mode (default): cadenas VALID/INVALID compatibles.
    if error is None:
        print(f"VALID: {args.card}")
        return 0
    print(f"INVALID: {error.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
