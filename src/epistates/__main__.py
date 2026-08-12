"""CLI read-only para validar contratos de Epistates."""

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Sequence

from .adapter import validate_adapter_capabilities
from .audit import validate_audit_binding, validate_audit_result
from .contracts import ValidationError, validate_task_card
from .dispatch import _MESSAGE_MAX_BYTES, validate_dispatch_receipt, validate_dispatch_receipt_binding
from .preflight import validate_preflight_binding, validate_preflight_result


_VALIDATORS = {
    "epistates/task-card/v1": validate_task_card,
    "epistates/audit-result/v1": validate_audit_result,
    "epistates/adapter-capabilities/v1": validate_adapter_capabilities,
    "epistates/preflight-result/v1": validate_preflight_result,
    "epistates/dispatch-receipt/v1": validate_dispatch_receipt,
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


def _binding_options_provided(args) -> bool:
    """True si cualquier opción de binding está presente (todas las schemas)."""
    return any(value is not None for value in (
        args.task_card, args.adapter_capabilities, args.run_id,
        args.attempt_id, args.expected_session_name, args.expected_command,
        args.message_file, args.preflight_result, args.max_preflight_age_seconds,
    ))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="epistates")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validar un artefacto sin ejecutar checks")
    validate.add_argument("card", type=Path, metavar="artifact")
    validate.add_argument("--task-card", type=Path, help="tarjeta requerida para ligar audit-result, preflight-result o dispatch-receipt")
    validate.add_argument("--adapter-capabilities", type=Path, help="adaptador requerido para ligar preflight-result o dispatch-receipt")
    validate.add_argument("--run-id", help="run esperado para audit-result, preflight-result o dispatch-receipt")
    validate.add_argument("--attempt-id", help="attempt esperado para audit-result, preflight-result o dispatch-receipt")
    validate.add_argument("--expected-session-name", help="sesion esperada para ligar preflight-result o dispatch-receipt")
    validate.add_argument("--expected-command", help="comando esperado para ligar preflight-result o dispatch-receipt")
    validate.add_argument("--message-file", type=Path, help="mensaje literal para ligar dispatch-receipt")
    validate.add_argument("--preflight-result", type=Path, help="preflight-result exacto para ligar dispatch-receipt")
    validate.add_argument("--max-preflight-age-seconds", help="política externa de frescura (s) para ligar dispatch-receipt")
    args = parser.parse_args(argv)
    try:
        artifact = _load_json(args.card)
        if not isinstance(artifact, dict) or artifact.get("schema") not in _VALIDATORS:
            raise ValidationError("schema ausente o no soportado")
        _VALIDATORS[artifact["schema"]](artifact)
        schema = artifact["schema"]
        if schema == "epistates/audit-result/v1":
            if args.task_card is None or args.run_id is None or args.attempt_id is None:
                raise ValidationError("audit-result requiere --task-card, --run-id y --attempt-id")
            if any(value is not None for value in (
                    args.adapter_capabilities, args.expected_session_name,
                    args.expected_command, args.message_file, args.preflight_result,
                    args.max_preflight_age_seconds)):
                raise ValidationError("opciones de binding sólo aplican a preflight-result o dispatch-receipt")
            task_card = _load_json(args.task_card)
            validate_audit_binding(artifact, task_card, args.run_id, args.attempt_id)
        elif schema == "epistates/preflight-result/v1":
            missing = []
            if args.task_card is None:
                missing.append("--task-card")
            if args.adapter_capabilities is None:
                missing.append("--adapter-capabilities")
            if args.run_id is None:
                missing.append("--run-id")
            if args.attempt_id is None:
                missing.append("--attempt-id")
            if args.expected_session_name is None:
                missing.append("--expected-session-name")
            if args.expected_command is None:
                missing.append("--expected-command")
            if missing:
                raise ValidationError("preflight-result requiere " + ", ".join(missing))
            if any(value is not None for value in (
                    args.message_file, args.preflight_result,
                    args.max_preflight_age_seconds)):
                raise ValidationError(
                    "--message-file, --preflight-result y --max-preflight-age-seconds sólo aplican a dispatch-receipt"
                )
            task_card = _load_json(args.task_card)
            adapter = _load_json(args.adapter_capabilities)
            validate_preflight_binding(
                artifact, task_card, adapter, args.run_id, args.attempt_id,
                args.expected_session_name, args.expected_command,
            )
        elif schema == "epistates/dispatch-receipt/v1":
            missing = []
            if args.task_card is None:
                missing.append("--task-card")
            if args.adapter_capabilities is None:
                missing.append("--adapter-capabilities")
            if args.preflight_result is None:
                missing.append("--preflight-result")
            if args.run_id is None:
                missing.append("--run-id")
            if args.attempt_id is None:
                missing.append("--attempt-id")
            if args.expected_session_name is None:
                missing.append("--expected-session-name")
            if args.expected_command is None:
                missing.append("--expected-command")
            if args.max_preflight_age_seconds is None:
                missing.append("--max-preflight-age-seconds")
            if args.message_file is None:
                missing.append("--message-file")
            if missing:
                raise ValidationError("dispatch-receipt requiere " + ", ".join(missing))
            try:
                expected_max_age = float(args.max_preflight_age_seconds)
            except (TypeError, ValueError):
                raise ValidationError("--max-preflight-age-seconds debe ser un número")
            task_card = _load_json(args.task_card)
            adapter = _load_json(args.adapter_capabilities)
            preflight_result = _load_json(args.preflight_result)
            message = _read_bounded_message(args.message_file, _MESSAGE_MAX_BYTES).decode("utf-8")
            validate_dispatch_receipt_binding(
                artifact, task_card, adapter, preflight_result,
                args.run_id, args.attempt_id,
                args.expected_session_name, args.expected_command,
                expected_max_age, message,
            )
        elif _binding_options_provided(args):
            raise ValidationError("opciones de binding sólo aplican a audit-result, preflight-result o dispatch-receipt")
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(f"VALID: {args.card}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
