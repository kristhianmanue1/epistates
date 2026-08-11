# Plan inicial — E1 contratos y conformidad

**Estado:** H1 y H2 cerrados; H3 en curso (Slice1 aceptado; cortes operativos
pendientes). **Fecha:** 2026-08-11. **Fuente:** definición fundacional y
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
- H2 — resultado de auditoría y transiciones: hecho; ronda adversarial final
  `proceed`.
- H3 — adaptador `opencode-tmux/v1` con preflight: en curso. Slice1
  implementado (contrato neutral `adapter-capabilities/v1` y preflight puro
  fail-closed con resultado portable `preflight-result/v1`) y aceptado tras
  ronda adversarial `proceed`; los cortes operativos siguen pendientes.

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

## Contrato H2

**Entradas:** contrato H1, estados del README y
[`architecture/0001-audit-state-v1.md`](architecture/0001-audit-state-v1.md).
**Salidas:** schema y validador `audit-result/v1`, máquina de estados pura,
fixtures y pruebas.

Definition of Done:

- una secuencia nominal alcanza `DONE` sólo desde `REVIEWING` con auditoría
  `OK/proceed` y evidencia completa;
- evidencia fallida o ausente no puede producir `OK`;
- estados terminales y transiciones desconocidas fallan cerrados;
- validar un resultado no ejecuta checks, no escribe estado y no inicia
  adaptadores;
- pruebas unitarias y fixtures positivos/adversariales quedan en verde;
- ronda adversarial independiente termina en `proceed` antes de cerrar H2.

La evidencia de cierre está en [`adversarial-h2.md`](adversarial-h2.md).

## Contrato H3 — Slice1

**Entradas:** contrato H2, README (roles del controlador/adaptador y flujo
operativo) y la corrección adversarial del análisis H3. **Salidas:** contrato
neutral `epistates/adapter-capabilities/v1`, preflight puro fail-closed y
resultado portable `epistates/preflight-result/v1`.

Slice1 es estrictamente declarativo y sin integración de procesos: no ejecuta
subprocess, no usa `tmux send-keys` y no consulta el reloj (`observed_at` se
inyecta). Separa expectativas (repositorio/worktree/rama/SHA base desde
`task_card.target`; `expected_session_name` y `expected_command` como argumentos
explícitos del controlador) de observaciones inyectadas por el host.

Definition of Done de Slice1:

- `adapter-capabilities/v1` valida identidad, plataformas (`darwin`, `linux`) y
  capabilities cerradas (`dispatch_literal`, `observe_session`, `capture_once`);
  `adapter_id` puede identificar `opencode-tmux` sin romper la neutralidad;
- el preflight liga repository, worktree, cwd (coincidencia exacta con
  `target.worktree`, no containment), branch, SHA, limpieza, sesión, pane vivo,
  comando observado y plataforma contra `adapter.platforms`;
- observaciones ausentes o mal tipadas producen `PreflightError`; nunca `ok`;
- `preflight-result/v1` lleva `schema`, `task_id`, `run_id`, `attempt_id`,
  `task_card_digest`, `adapter_digest`, `adapter_id`, `observed_at`, `outcome`,
  `reasons` (únicos y en orden determinista) y `observed` saneado;
- el CLI registra ambos schemas y, para `preflight-result`, exige binding
  completo (`--task-card`, `--adapter-capabilities`, `--run-id`, `--attempt-id`,
  `--expected-session-name`, `--expected-command`);
- la suite unittest termina en verde.

La evidencia de aceptación de Slice1 está en
[`adversarial-h3.md`](adversarial-h3.md). H3 completo permanece abierto hasta
implementar y auditar los sub-cortes posteriores: observación real del host,
entrega literal, pausa sin polling e inspección única.

### Reproducibilidad del DoD

El intérprete del auditor es el venv editable del worktree principal:

```bash
/Users/krisnova/www/aria/epistates/.venv/bin/python
```

Ese venv importa `epistates` desde `/Users/krisnova/www/aria/epistates/src`,
no desde este worktree. Para ejecutar la suite contra **este** worktree de forma
reproducible se requiere `PYTHONPATH=src`:

```bash
PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Sin `PYTHONPATH=src` no se prueba este worktree. Los validadores CLI análogos:

```bash
PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m epistates validate fixtures/adapter-capabilities-opencode-tmux.json
PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m epistates validate fixtures/preflight-result-ok.json \
  --task-card fixtures/task-card-valid.json \
  --adapter-capabilities fixtures/adapter-capabilities-opencode-tmux.json \
  --run-id run-001 --attempt-id attempt-001 \
  --expected-session-name epistates-opencode --expected-command idle
```
