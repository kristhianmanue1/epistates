#!/usr/bin/env python3
"""Comprueba destinos locales de enlaces Markdown seleccionados."""

from __future__ import annotations

import re
import sys
from pathlib import Path


LINK_RE = re.compile(r"\[[^]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "data:")


def local_destinations(path: Path) -> list[Path]:
    """Devuelve destinos locales enlazados por ``path`` sin fragmentos."""
    destinations: list[Path] = []
    for raw in LINK_RE.findall(path.read_text(encoding="utf-8")):
        target = raw.strip().strip("<>").split("#", 1)[0]
        if not target or target.startswith(EXTERNAL_PREFIXES):
            continue
        destinations.append((path.parent / target).resolve())
    return destinations


def project_root(path: Path) -> Path:
    """Encuentra la raíz del repo de ``path`` o usa su directorio como límite."""
    current = path.resolve().parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return path.resolve().parent


def check_paths(paths: list[Path]) -> list[str]:
    """Devuelve un error por cada destino inexistente o fuera del proyecto."""
    failures: list[str] = []
    for path in paths:
        root = project_root(path)
        for destination in local_destinations(path):
            try:
                destination.relative_to(root)
            except ValueError:
                failures.append(f"{path}: enlace local fuera del proyecto: {destination}")
            else:
                if not destination.exists():
                    failures.append(f"{path}: enlace local inexistente: {destination}")
    return failures


def main(argv: list[str] | None = None) -> int:
    raw_paths = sys.argv[1:] if argv is None else argv
    if not raw_paths:
        print("uso: check_documentation_links.py ARCHIVO.md [...]")
        return 2
    paths = [Path(raw).resolve() for raw in raw_paths]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"BLOQ — archivo inexistente: {path}")
        return 2
    failures = check_paths(paths)
    if failures:
        print("BLOQ — enlaces locales inválidos")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"OK — {len(paths)} archivo(s) con enlaces locales válidos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
