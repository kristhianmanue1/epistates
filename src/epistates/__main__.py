"""CLI read-only para validar contratos de Epistates."""

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .contracts import ValidationError, validate_task_card


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="epistates")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validar una tarjeta sin ejecutar sus checks")
    validate.add_argument("card", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.card.open(encoding="utf-8") as handle:
            validate_task_card(json.load(handle))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(f"VALID: {args.card}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
