# Plan inicial — E1 contratos y conformidad

**Estado:** H1 y H2 cerrados; H3 en curso (Slice1 y Slice2 aceptados; cortes
operativos restantes abiertos).
**Fecha:** 2026-08-11. **Fuente:** definición fundacional y protocolo técnico
del piloto.

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
  ronda adversarial `proceed`. Slice2 implementado y aceptado tras auditoría
  independiente (observación read-only real del host vía runner inyectable y
  `observe_opencode_tmux`); los cortes operativos restantes siguen abiertos.

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

## Contrato H3 — Slice2

**Entradas:** contrato H2, Slice1 aceptado y la responsabilidad del controlador
de observar proceso, sesión y repositorio como dimensiones distintas.
**Salidas:** runner read-only inyectable (`ProductionHostRunner` + protocolo
`HostRunner`) y observador `observe_opencode_tmux` que produce las 11 claves que
`evaluate_preflight` consume.

Slice2 es observación real y estrictamente read-only: no entrega instrucciones
(no usa `tmux send-keys`), no captura contenido (no usa `capture-pane`), no crea
ni destruye sesiones (no usa `kill-session` ni `new-session`), y no autoriza:
`observe_opencode_tmux` no llama a `evaluate_preflight`; sólo reúne el estado
del host para que el preflight decida.

Definition of Done de Slice2 (implementado y aceptado):

- el runner expone sólo operaciones cerradas (`git_toplevel`, `git_head`,
  `git_branch`, `git_status`, `tmux_list_panes`): construye argv internamente y
  no acepta argv arbitrario del caller;
- subprocess se ejecuta con `shell=False`, `stdin=DEVNULL`, argv list, `cwd`
  validado, entorno mínimo construido desde cero (sin heredar `HOME`, `PATH`,
  `GIT_*` ni `TMUX_*`; locale `C` y `GIT_OPTIONAL_LOCKS=0`,
  `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`) y salida capturada
  como bytes decodificada UTF-8 estricto; `timeout_seconds` es un número finito
  en el rango cerrado `(0, 60]`;
- falla cerrado ante timeout, executable ausente o inaccesible (OSError, incluido
  PermissionError), exit no cero, stderr no vacío en exit 0, salida combinada
  sobre el límite (comprobada antes de interpretar exit), byte NUL, UTF-8
  inválido o forma inesperada; los mensajes de error no incluyen stdout/stderr
  potencialmente sensibles;
- Git usa sólo los equivalentes fijos de `rev-parse --show-toplevel`,
  `rev-parse HEAD`, `branch --show-current` y
  `status --porcelain=v1 --untracked-files=normal`; tmux usa sólo
  `list-panes -t SESSION -F` con `pane_dead`, `pane_current_command` y
  `pane_current_path`, validando `SESSION` con un patrón cerrado y exigiendo
  exactamente un pane y tres campos. El framing usa un delimitador **printable**
  (`|`): tmux 3.6a sanitiza los caracteres de control del formato (un TAB
  literal se sustituye por `_` y colapsa el split); una colisión de `|` en un
  valor produce más de tres campos y se rechaza por fail-closed;
- `observe_opencode_tmux` recibe `task_card`, `session_name`, `observed_at`,
  `platform_name` y `runner` inyectado (no consulta reloj ni plataforma global);
  produce exactamente las 11 claves esperadas en orden determinista y sin
  mutar entradas;
- el worktree se valida como absoluto, normalizado y distinto de raíz antes de
  cualquier subprocess; las observaciones pasan crudas (sin seguir symlinks ni
  normalizar para forzar coincidencia).

Limitaciones locales v1 documentadas con honestidad:

- `observed_repository` se deriva como `basename` del *git toplevel*: v1 no
  consulta la configuración de remotos, así que un directorio con nombre
  distinto al repositorio esperado produce `repository_mismatch` en el preflight;
- `max_output_bytes` se aplica *después* de capturar la salida en memoria: no es
  aislamiento de memoria del SO, sólo impide devolver o decodificar el exceso.

La evidencia y los riesgos residuales aceptados están en
[`adversarial-h3-slice2.md`](adversarial-h3-slice2.md). La decisión es
`proceed` para Slice2; H3 completo permanece abierto.

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
