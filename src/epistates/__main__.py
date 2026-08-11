"""CLI read-only para validar contratos de Epistates."""

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Sequence

from .adapter import validate_adapter_capabilities
from .audit import validate_audit_binding, validate_audit_result
from .contracts import ValidationError, validate_task_card
from .preflight import validate_preflight_binding, validate_preflight_result


_VALIDATORS = {
    "epistates/task-card/v1": validate_task_card,
    "epistates/audit-result/v1": validate_audit_result,
    "epistates/adapter-capabilities/v1": validate_adapter_capabilities,
    "epistates/preflight-result/v1": validate_preflight_result,
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


def _binding_options_provided(args) -> bool:
    return any(value is not None for value in (
        args.task_card, args.adapter_capabilities, args.run_id,
        args.attempt_id, args.expected_session_name, args.expected_command,
    ))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="epistates")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validar un artefacto sin ejecutar checks")
    validate.add_argument("card", type=Path, metavar="artifact")
    validate.add_argument("--task-card", type=Path, help="tarjeta requerida para ligar audit-result o preflight-result")
    validate.add_argument("--adapter-capabilities", type=Path, help="adaptador requerido para ligar preflight-result")
    validate.add_argument("--run-id", help="run esperado para audit-result o preflight-result")
    validate.add_argument("--attempt-id", help="attempt esperado para audit-result o preflight-result")
    validate.add_argument("--expected-session-name", help="sesion esperada para ligar preflight-result")
    validate.add_argument("--expected-command", help="comando esperado para ligar preflight-result")
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
                    args.adapter_capabilities, args.expected_session_name, args.expected_command)):
                raise ValidationError("opciones de binding sólo aplican a preflight-result")
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
            task_card = _load_json(args.task_card)
            adapter = _load_json(args.adapter_capabilities)
            validate_preflight_binding(
                artifact, task_card, adapter, args.run_id, args.attempt_id,
                args.expected_session_name, args.expected_command,
            )
        elif _binding_options_provided(args):
            raise ValidationError("opciones de binding sólo aplican a audit-result o preflight-result")
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(f"VALID: {args.card}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
