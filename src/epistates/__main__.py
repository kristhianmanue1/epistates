"""CLI para validar contratos y descubrir la superficie de Epistates.

Carácter estático vs. I/O:

- ``--version``, ``--help`` y ``describe --format json`` son estáticos: no
  ejecutan subprocess, no abren sockets, no leen el reloj ni sondean el host.
- ``validate`` hace I/O de filesystem (lee archivos JSON del disco) pero no
  inicia adaptadores ni resuelve checks. La validez de un artefacto no
  constituye autorización.

Superficie:

- ``epistates --version``: versión single-source del paquete (exit 0).
- ``epistates validate <artifact> [--binding ...]``: valida artefacto + binding.
- ``epistates describe --format json``: documento estático
  ``epistates/discovery/v1`` (un único JSON determinista en stdout, stderr
  vacío, ASCII-escapado y robusto ante locale/encoding).

No existe CLI operativo para observe/dispatch/review/audit: esas operaciones
requieren autoridad externa y runners inyectados, y quedan fuera del alcance
estático de descubrimiento.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

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


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"clave JSON duplicada: {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_keys)


def _read_bounded_message(path: Path, limit: int) -> bytes:
    """Lee el mensaje con barrera anti-TOCTOU.

    ``stat`` es sólo una optimización (fast path): la barrera real es leer como
    mucho ``limit + 1`` bytes y rechazar si sobra cualquiera. Así un archivo que
    crezca entre ``stat`` y ``read`` (o un ``stat`` que mienta) nunca carga un
    archivo arbitrariamente grande.
    """
    if path.stat().st_size > limit:
        raise ValidationError("message-file excede el límite de bytes")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValidationError("message-file excede el límite de bytes")
    return raw


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


class _SafeArgumentParser(argparse.ArgumentParser):
    """Parser que sanea argv reflejado en errores antes de imprimir a stderr."""

    def error(self, message: str):  # type: ignore[override]
        super().error(_escape_control_chars(message))


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
    return "\n".join(lines)


def _build_parser() -> "_SafeArgumentParser":
    """Construye el parser con ayuda, --version, validate y describe.

    Usa ``_SafeArgumentParser`` (sanitiza argv en errores) y ``parser_class``
    para que los subparsers hereden el mismo comportamiento.
    """
    parser = _SafeArgumentParser(
        prog="epistates",
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
        dest="command", required=True, parser_class=_SafeArgumentParser
    )

    validate = subparsers.add_parser(
        "validate",
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    # ``main`` NO muta los streams del caller (encoding/errors). La salida
    # estatica (--version/--help/describe) es ASCII y robusta bajo cualquier
    # locale/encoding; describe se serializa ASCII-escapado. El saneamiento y
    # JSON estable de la salida textual de validate queda reservado a Slice2.
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "describe":
        # Estatico y determinista: stdout = unico JSON ASCII, stderr vacio.
        sys.stdout.write(render_discovery_json())
        return 0
    try:
        artifact = _load_json(args.card)
        if not isinstance(artifact, dict) or artifact.get("schema") not in _VALIDATORS:
            raise ValidationError("schema ausente o no soportado")
        schema = artifact["schema"]
        # Validación estructural propia del schema.
        _VALIDATORS[schema](artifact)
        # Modo puente del audit-result: cuando lleva ``review_evidence_digest``
        # se exige el binding completo a review-evidence + decisión inyectada.
        audit_review_mode = (
            schema == "epistates/audit-result/v1"
            and "review_evidence_digest" in artifact
        )
        if audit_review_mode:
            # En modo puente todas las opciones son aplicables y requeridas.
            _require_audit_review_options(args)
        else:
            # Comprobación de aplicabilidad de opciones (antes del binding).
            _check_applicability(schema, args)
            if schema in _APPLICABLE and _APPLICABLE[schema]:
                _require_applicable(schema, args)
        # Binding por schema.
        if schema == "epistates/audit-result/v1":
            task_card = _load_json(args.task_card)
            if audit_review_mode:
                adapter = _load_json(args.adapter_capabilities)
                preflight_result = _load_json(args.preflight_result)
                dispatch_receipt = _load_json(args.dispatch_receipt)
                human_notice = _load_json(args.human_notice)
                review_evidence = _load_json(args.review_evidence)
                expected_max_preflight = _parse_number(
                    args.max_preflight_age_seconds, "--max-preflight-age-seconds"
                )
                expected_max_dispatch = _parse_number(
                    args.max_dispatch_age_seconds, "--max-dispatch-age-seconds"
                )
                expected_max_notice = _parse_number(
                    args.max_notice_age_seconds, "--max-notice-age-seconds"
                )
                message = _read_bounded_message(
                    args.message_file, _MESSAGE_MAX_BYTES
                ).decode("utf-8")
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
            task_card = _load_json(args.task_card)
            adapter = _load_json(args.adapter_capabilities)
            validate_preflight_binding(
                artifact, task_card, adapter, args.run_id, args.attempt_id,
                args.expected_session_name, args.expected_command,
            )
        elif schema == "epistates/dispatch-receipt/v1":
            task_card = _load_json(args.task_card)
            adapter = _load_json(args.adapter_capabilities)
            preflight_result = _load_json(args.preflight_result)
            expected_max_age = _parse_number(
                args.max_preflight_age_seconds, "--max-preflight-age-seconds"
            )
            message = _read_bounded_message(
                args.message_file, _MESSAGE_MAX_BYTES
            ).decode("utf-8")
            validate_dispatch_receipt_binding(
                artifact, task_card, adapter, preflight_result,
                args.run_id, args.attempt_id,
                args.expected_session_name, args.expected_command,
                expected_max_age, message,
            )
        elif schema == "epistates/human-notice/v1":
            task_card = _load_json(args.task_card)
            adapter = _load_json(args.adapter_capabilities)
            dispatch_receipt = _load_json(args.dispatch_receipt)
            expected_max_dispatch = _parse_number(
                args.max_dispatch_age_seconds, "--max-dispatch-age-seconds"
            )
            validate_human_notice_binding(
                artifact, task_card, adapter, dispatch_receipt,
                args.run_id, args.attempt_id,
                args.expected_session_name, expected_max_dispatch,
            )
        elif schema == "epistates/review-evidence/v1":
            task_card = _load_json(args.task_card)
            adapter = _load_json(args.adapter_capabilities)
            preflight_result = _load_json(args.preflight_result)
            dispatch_receipt = _load_json(args.dispatch_receipt)
            human_notice = _load_json(args.human_notice)
            expected_max_preflight = _parse_number(
                args.max_preflight_age_seconds, "--max-preflight-age-seconds"
            )
            expected_max_dispatch = _parse_number(
                args.max_dispatch_age_seconds, "--max-dispatch-age-seconds"
            )
            expected_max_notice = _parse_number(
                args.max_notice_age_seconds, "--max-notice-age-seconds"
            )
            message = _read_bounded_message(
                args.message_file, _MESSAGE_MAX_BYTES
            ).decode("utf-8")
            validate_review_evidence_binding(
                artifact, task_card, adapter, preflight_result,
                dispatch_receipt, human_notice,
                args.run_id, args.attempt_id,
                args.expected_session_name, args.expected_command,
                expected_max_preflight, message,
                expected_max_dispatch, expected_max_notice,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(f"VALID: {args.card}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
