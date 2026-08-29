# Release Gate — Epistates 0.1.0-alpha.2

**Versión PEP 440:** `0.1.0a2` · **Tag futuro:** `v0.1.0-alpha.2`
**Estado:** candidata local en preparación; **NO PUBLICADA**.

Este gate certifica exclusivamente el corte alpha.2. El cierre histórico de
alpha.1 permanece en [`release-gate.md`](release-gate.md). Pasar este gate no
autoriza tag, GitHub Release ni PyPI.

## Alcance funcional del corte

- H1–H4: contratos, validación, auditoría, discovery, schemas y onboarding.
- E3: recibos locales atómicos, inbox/reconciliación y adaptador macOS kqueue
  que sólo señala “hay trabajo”.
- E4: guard, kill switch, cuota/nonce, ledger, reserva atómica, coordinador,
  observación/reconciliación terminal y transportes OpenCode 1.18.25.
- E4 permanece **interno e inactivo**: no existe daemon, wiring runtime, polling
  automático, sesión automática ni wake habilitado.

## Gate ejecutable

1. Árbol y diff acotados; tarjeta válida; enlaces y secretos revisados.
2. Suite completa en Python 3.9 y 3.12.
3. CI GitHub en macOS/Linux × Python 3.9/3.12.
4. Versión single-source `0.1.0a2` coherente con metadata y wheel.
5. Dos copias fuente independientes construidas con el mismo
   `SOURCE_DATE_EPOCH`; wheel byte-idéntico por nombre, tamaño y SHA-256.
6. Inventario exacto de módulos, schemas, onboarding y metadata.
7. Instalación del wheel sin dependencias en venvs limpios Python 3.9/3.12.
8. Smoke desde cwd vacío, sin `PYTHONPATH`: import/version, CLI, discovery,
   schemas, onboarding y validación nominal/inválida.
9. Ausencia de repo/docs/tests/fixtures y secretos dentro del wheel.
10. Ronda adversarial fresca del artefacto final.

## Evidencia

Pendiente. Se completará con SHA de candidata, epoch, hashes, inventario,
resultados CI/smoke y riesgos residuales. Hasta entonces el veredicto es
`BLOCKED` para release.
