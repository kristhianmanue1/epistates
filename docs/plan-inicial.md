# Plan inicial — E1 contratos y conformidad

**Estado:** H1 cerrado; H2 pendiente. **Fecha:** 2026-08-11. **Fuente:** definición fundacional y
protocolo técnico del piloto.

## Objetivo y criterio de cierre

Crear una base read-only que permita rechazar una tarjeta de trabajo ambigua
antes de preparar worktrees, sesiones o agentes externos.

El primer cierre exige que una tarjeta válida y fixtures adversariales sean
validados localmente sin resolver ni ejecutar sus checks, ni iniciar un proceso
externo.

## Hitos

- H1 — contrato `task-card/v1`: schema, fixtures y validador local. Hecho;
  ronda adversarial final `proceed` tras tres iteraciones de endurecimiento.
- H2 — resultado de auditoría y transiciones: pendiente.
- H3 — adaptador `opencode-tmux/v1` con preflight: pendiente.

## Contrato H1

**Entradas:** `README.md`, el protocolo técnico y las prácticas ADRC de
Escrubery. **Salidas:** schema versionado, fixtures y CLI read-only.

Definition of Done:

- `python -m unittest discover -s tests -p 'test_*.py'` termina con exit 0.
- `python -m epistates validate fixtures/task-card-valid.json` termina con exit 0.
- una tarjeta sin prohibiciones explícitas, autoridad, evidencia o con ruta fuera
  del worktree termina con exit distinto de 0.
- el validador sólo acepta IDs de un catálogo; no resuelve checks ni inicia
  adaptadores.

## Decisiones de diseño

- AN-KLA conserva continuidad local; lo recuperado es dato y nunca autoridad.
- Escrubery aporta el proceso ADRC, no una dependencia runtime.
- La tarjeta no concede operaciones protegidas por omisión: commit, push, PR,
  merge y release deben estar explícitamente prohibidas o autorizadas por una
  decisión posterior del mantenedor.
- H1 no crea worktrees, ramas, sesiones ni procesos.
- Los checks se declaran mediante identificadores de un catálogo del runtime; una
  tarjeta no puede transportar comandos ejecutables.
- `authority` registra la concesión esperada de la tarjeta, pero no constituye
  por sí mismo una prueba de autoridad: H2 deberá ligarla a una decisión del
  mantenedor y conservar evidencia independiente.

La evidencia de cierre de H1 está en [`adversarial-h1.md`](adversarial-h1.md).
