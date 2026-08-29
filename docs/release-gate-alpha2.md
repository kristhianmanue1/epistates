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
3. CI local en macOS con Python 3.9/3.12. La matriz GitHub macOS/Linux se
   conserva para ejecución manual y revalidación cuando vuelva la cuota.
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

El run GitHub Actions
[`33225053925`](https://github.com/kristhianmanue1/epistates/actions/runs/33225053925)
no inició ningún step: GitHub lo bloqueó por límite de uso/facturación. Por
decisión explícita del mantenedor, ese bloqueo es una limitación externa, no un
fallo del código. Para este corte, la evidencia autoritativa será la suite local
en macOS con Python 3.9 y 3.12. Linux queda **NO VERIFICADO** y no debe inferirse
del workflow preparado.

El resto de la evidencia está pendiente. Se completará con SHA de candidata,
epoch, hashes, inventario, resultados locales/smoke y riesgos residuales. Hasta
entonces el veredicto es `BLOCKED` para release.
