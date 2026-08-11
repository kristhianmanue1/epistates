"""CLI read-only para validar contratos de Epistates."""

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .audit import validate_audit_binding, validate_audit_result
from .contracts import ValidationError, validate_task_card


_VALIDATORS = {
    "epistates/task-card/v1": validate_task_card,
    "epistates/audit-result/v1": validate_audit_result,
}


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"clave JSON duplicada: {key!r}")
        result[key] = value
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="epistates")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validar un artefacto sin ejecutar checks")
    validate.add_argument("card", type=Path, metavar="artifact")
    validate.add_argument("--task-card", type=Path, help="tarjeta requerida para ligar un audit-result")
    validate.add_argument("--run-id", help="run esperado para un audit-result")
    validate.add_argument("--attempt-id", help="attempt esperado para un audit-result")
    args = parser.parse_args(argv)
    try:
        with args.card.open(encoding="utf-8") as handle:
            artifact = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(artifact, dict) or artifact.get("schema") not in _VALIDATORS:
            raise ValidationError("schema ausente o no soportado")
        _VALIDATORS[artifact["schema"]](artifact)
        if artifact["schema"] == "epistates/audit-result/v1":
            if args.task_card is None or args.run_id is None or args.attempt_id is None:
                raise ValidationError("audit-result requiere --task-card, --run-id y --attempt-id")
            with args.task_card.open(encoding="utf-8") as handle:
                task_card = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
            validate_audit_binding(artifact, task_card, args.run_id, args.attempt_id)
        elif any(value is not None for value in (args.task_card, args.run_id, args.attempt_id)):
            raise ValidationError("opciones de binding sólo aplican a audit-result")
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(f"VALID: {args.card}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
