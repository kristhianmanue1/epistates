# Ronda adversarial — H1 task-card/v1

**Fecha:** 2026-08-11. **Decisión final:** `proceed`.

## Alcance

Revisión independiente del schema, validador, fixtures, pruebas y coherencia con
el protocolo fundacional. Sólo se evaluaron corrección, autoridad, aislamiento y
requisitos; no se realizaron mutaciones Git.

## Hallazgos corregidos

- autoridad y evidencia no estructuradas;
- checks transportados como comandos arbitrarios;
- rutas permitidas o entradas capaces de escapar del worktree;
- tipos JSON capaces de provocar traceback en vez de rechazo cerrado;
- divergencias entre schema y validador para texto vacío;
- worktrees relativos, raíz, no normalizados o con doble barra inicial;
- catálogo insuficiente de operaciones Git y de worktrees protegidas;
- cobertura adversarial insuficiente.

## Evidencia final

- `python -m unittest discover -s tests -p 'test_*.py'` → 11 tests, `OK`.
- `python -m epistates validate fixtures/task-card-valid.json` → `VALID`.
- fixture sin `forbidden_operations` → `INVALID` y exit distinto de cero.
- AN-KLA `verify` → `ok: true`; memoria local sin registros.

## Riesgo residual aceptado

`authority` es una declaración dentro de la tarjeta, no una atestación. H2 debe
ligar esa declaración a evidencia externa de la decisión del mantenedor antes de
permitir una transición material.
