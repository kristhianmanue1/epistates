"""CLI read-only para validar contratos de Epistates."""

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Sequence

from .adapter import validate_adapter_capabilities
from .audit import validate_audit_binding, validate_audit_result
from .contracts import ValidationError, validate_task_card
from .dispatch import _MESSAGE_MAX_BYTES, validate_dispatch_receipt, validate_dispatch_receipt_binding
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

# Opciones de binding reconocidas por el CLI (todas las schemas).
_ALL_BINDING_OPTIONS = (
    "task_card", "adapter_capabilities", "run_id", "attempt_id",
    "expected_session_name", "expected_command", "message_file",
    "preflight_result", "max_preflight_age_seconds",
    "dispatch_receipt", "human_notice", "max_dispatch_age_seconds",
    "max_notice_age_seconds",
)

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
    "epistates/review-evidence/v1": frozenset(_ALL_BINDING_OPTIONS),
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


def _parse_number(value: Optional[str], name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} debe ser un número")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="epistates")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validar un artefacto sin ejecutar checks")
    validate.add_argument("card", type=Path, metavar="artifact")
    validate.add_argument("--task-card", type=Path)
    validate.add_argument("--adapter-capabilities", type=Path)
    validate.add_argument("--run-id")
    validate.add_argument("--attempt-id")
    validate.add_argument("--expected-session-name")
    validate.add_argument("--expected-command")
    validate.add_argument("--message-file", type=Path)
    validate.add_argument("--preflight-result", type=Path)
    validate.add_argument("--max-preflight-age-seconds")
    validate.add_argument("--dispatch-receipt", type=Path)
    validate.add_argument("--human-notice", type=Path)
    validate.add_argument("--max-dispatch-age-seconds")
    validate.add_argument("--max-notice-age-seconds")
    args = parser.parse_args(argv)
    try:
        artifact = _load_json(args.card)
        if not isinstance(artifact, dict) or artifact.get("schema") not in _VALIDATORS:
            raise ValidationError("schema ausente o no soportado")
        schema = artifact["schema"]
        # Validación estructural propia del schema.
        _VALIDATORS[schema](artifact)
        # Comprobación de aplicabilidad de opciones (antes del binding).
        _check_applicability(schema, args)
        if schema in _APPLICABLE and _APPLICABLE[schema]:
            _require_applicable(schema, args)
        # Binding por schema.
        if schema == "epistates/audit-result/v1":
            task_card = _load_json(args.task_card)
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
