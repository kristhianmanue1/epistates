# Plan inicial — E1 contratos y conformidad

**Estado:** H1, H2 y H3 cerrados; Slice1–Slice5 aceptados tras rondas
adversariales independientes. El siguiente gate es preparar la primera release
experimental.
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
- H3 — adaptador `opencode-tmux/v1` con ciclo supervisado completo: cerrado.
  Slice1
  implementado (contrato neutral `adapter-capabilities/v1` y preflight puro
  fail-closed con resultado portable `preflight-result/v1`) y aceptado tras
  ronda adversarial `proceed`. Slice2 implementado y aceptado tras auditoría
  independiente (observación read-only real del host vía runner inyectable y
  `observe_opencode_tmux`). Slice3 implementado y aceptado tras auditoría
  independiente (entrega literal opencode-tmux y recibo
  `dispatch-receipt/v1`). Slice4 implementado y aceptado tras auditoría
  independiente (aviso humano cerrado `human-notice/v1`, frontera de inspección
  `ReviewRunner` y evidencia portable `review-evidence/v1`). Slice5
  implementado, corregido y aceptado tras auditoría independiente (puente
  `review-evidence/v1` → `audit-result/v1` → `apply_audit` puro, con política
  externa de timestamp, autoridad inyectada y anti-downgrade estructural; sin
  ejecución ni automatización).

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

## Contrato H3 — Slice3

**Entradas:** contrato H2, Slice1 y Slice2 aceptados, y la responsabilidad del
controlador de entregar instrucciones literales al ejecutor sin convertirse en
un deputy. **Salidas:** frontera de dispatch separada del `HostRunner`
read-only (`TmuxLiteralDispatcher` + protocolo `LiteralDispatcher`), función de
entrega `dispatch_literal_opencode_tmux` y recibo portable
`epistates/dispatch-receipt/v1`.

Slice3 es **sólo la entrega literal**: no implementa captura (`capture-pane`),
ni notificación automática de finalización, ni auditoría post-ejecución. Esas
capacidades siguen fuera de este corte y no quedan autorizadas por este
documento. Tras el éxito completo el controlador deriva `WAITING_EXTERNAL` y se
detiene: no observa nada después de Enter.

Definition of Done de Slice3 (implementado y aceptado):

- la frontera de dispatch está **separada** del `HostRunner` read-only:
  `TmuxLiteralDispatcher` sólo emite `tmux send-keys` y no reutiliza las
  operaciones de observación; `dispatch_literal_opencode_tmux` no acepta ni
  construye argv del caller;
- `dispatch_literal_opencode_tmux` valida **fail-closed el binding completo** de
  un `preflight-result/v1` con `outcome == ok` antes de cualquier efecto; si el
  preflight está bloqueado o mal ligado, lanza `DispatchError` **sin ninguna
  llamada** al dispatcher;
- exige `current_state == PREPARED`; valida sesión, `dispatched_at` inyectado,
  mensaje acotado y **política de frescura** antes de enviar;
- el recibo se liga al **preflight exacto** mediante `preflight_result_digest`,
  y el binding recibe/valida el preflight completo (outcome ok, IDs, sesión y
  `expected_command`);
- **política de frescura inyectada** `max_preflight_age_seconds` finita, positiva
  y acotada (techo 3600s): `dispatched_at` no puede preceder a `observed_at` ni
  exceder la edad máxima. Todo antes de efectos. El binding recibe la política
  **externa** del controlador (`expected_max_preflight_age_seconds`), valida los
  mismos límites, exige **igualdad exacta** con el valor del recibo (impide
  auto-ampliación) y rederiva la frescura con la política externa: nunca confía
  sólo en el recibo;
- el mensaje se valida con la **misma** función `_validate_message` en
  orquestación, dispatcher público y binding; longitud UTF-8 mínima 1;
- la entrega usa **exactamente dos** llamadas cerradas e inyectables, en orden:
  (1) `tmux send-keys -l -t SESSION -- MESSAGE` (literal, argv list, `shell=False`,
  terminador `--` antes del mensaje) y (2) `tmux send-keys -t SESSION Enter` en
  llamada separada. El caller nunca aporta argv ni se concatena shell;
- el mensaje rechaza NUL, surrogates y todo control C0 excepto LF (más DEL);
  preserva texto multilínea literal. TAB y CR se rechazan como controles
  peligrosos en contexto terminal;
- el dispatcher de producción usa executable absoluto, timeout finito en
  `(0, 60]`, entorno mínimo construido desde cero (sin `PATH`/`HOME`/`TMUX*`) y
  stdout/stderr/exit estrictos (cualquier byte en stdout/stderr o exit no cero
  es anomalía). Aplica validación completa de sesión y mensaje **aun en uso
  directo**;
- **pre cálculo completo antes del primer send**: digests (tarjeta, adaptador,
  preflight, mensaje), transición `PREPARED -> DISPATCHED -> WAITING_EXTERNAL` y
  recibo base se calculan antes de llamar al dispatcher. Tras un Enter exitoso
  no queda canonicalización, validación ni transición capaz de lanzar;
- **no reintenta automáticamente** con **tres categorías** de fallo:
  `DispatchError` (pre-efecto, nada intentado), `IndeterminateDispatchError`
  (fase 1 intentada y fallada ambiguamente; el literal pudo entregarse) y
  `PartialDispatchError` (literal confirmado, Enter indeterminado). Ninguna
  reintenta: un reintento duplicaría el literal;
- el recibo `dispatch-receipt/v1` **no guarda el prompt**: sólo IDs/digests
  ligados (incluido `preflight_result_digest`), sesión, `dispatched_at` inyectado,
  `max_preflight_age_seconds`, digest y longitud UTF-8 del mensaje,
  `phases_confirmed == [send_literal, send_enter]` (orden fijado por schema con
  `prefixItems`/`items:false`), `final_state == WAITING_EXTERNAL` y
  `confirms == "technical_transport_only"`;
- tras éxito completo deriva `DISPATCHED` y `WAITING_EXTERNAL` (precalculados)
  y no observa nada después de Enter (sin `capture-pane`, sin `list-panes`, sin
  polling);
- el CLI registra `dispatch-receipt/v1`, exige binding completo (`--task-card`,
  `--adapter-capabilities`, `--preflight-result`, `--run-id`, `--attempt-id`,
  `--expected-session-name`, `--expected-command`, `--max-preflight-age-seconds`
  y `--message-file`), lee el `--message-file` de forma **acotada y
  anti-TOCTOU** (como mucho `límite+1` bytes; `stat` es sólo optimización) y
  rechaza de forma global cualquier opción de binding inaplicable al schema
  (incluidos `--preflight-result` y `--max-preflight-age-seconds`): ninguna
  opción inaplicable se ignora silenciosamente;
- la suite unittest termina en verde.

Decisiones de diseño de Slice3:

- **`send-keys -l` + `--` para el literal.** `-l` (literal) envía el texto como
  bytes y nunca como nombre de tecla; `--` termina opciones para que un mensaje
  que empiece en `-` no se interprete como flag. Enter va en llamada separada
  **sin** `-l` para que tmux lo interprete como pulsación y complete la entrada.
- **Tres categorías, no dos.** Un fallo de fase 1 **no** implica "nada
  entregado": una vez invocado `send_literal_text`, timeout/OSError/exit anómalo
  son resultado **indeterminado** (el literal pudo entregarse). De ahí
  `IndeterminateDispatchError`, distinta del `DispatchError` pre-efecto. La fase
  2 mantiene `PartialDispatchError` (literal confirmado, Enter indeterminado).
  Ninguna categoría reintenta: la duplicación silenciosa queda excluida.
- **Pre cálculo antes del efecto.** Todo lo que pueda fallar (digests,
  transición, recibo) se calcula antes del primer send. Un Enter exitoso sólo
  devuelve el resultado precalculado: no puede fallar tras el efecto.
- **Frescura externa, no auto-amplificable.** El recibo registra
  `preflight_result_digest` y `max_preflight_age_seconds`, pero el binding no
  confía en ese último: recibe la política externa del controlador
  (`expected_max_preflight_age_seconds`), exige igualdad exacta y re_deriva la
  frescura con ella. Así mutar `dispatched_at` y `max_preflight_age_seconds` en
  un recibo no permite evadir la política del controlador.
- **Lectura anti-TOCTOU del message-file.** `stat` es sólo una optimización; la
  barrera real es leer como mucho `límite+1` bytes y rechazar si sobra. Un
  archivo que crezca entre `stat` y `read` (o un `stat` mentiroso) nunca se
  carga arbitrariamente grande.
- **Política de mensaje compartida.** `_validate_message` es la única política,
  usada idénticamente en orquestación, dispatcher público y binding, para que
  las tres capas coincidan y un mensaje vacío no sea aceptable en ninguna.
- **Sin socket `-L`/`-S`.** v1 asume el socket tmux por defecto derivado del
  UID. El entorno mínimo excluye `TMUX`/`TMUX_TMPDIR` para que el caller no
  redirija el socket. Soportar sockets explícitos queda para un corte posterior.
- **Recibo = transporte, no comprensión.** `confirms == "technical_transport_only"`
  deja explícito que el recibo atestigua que tmux aceptó `send-keys`, no que el
  agente leyó, comprendió o acató la instrucción.
- **TAB y CR rechazados.** Sólo LF es necesario para texto multilínea. En un
  terminal TAB dispara completado y CR es ambiguo; rechazarlos es la opción
  fail-closed.

Riesgos residuales aceptados de Slice3:

- el recibo confirma **transporte técnico**, no recepción/comprensión por el
  agente: si el TUI del ejecutor no procesó el literal, el recibo lo omite. La
  auditoría post-ejecución (futura) es la que contrasta el reporte con evidencia
  independiente;
- `max_output_bytes` se aplica después de que `subprocess.run` captura la
  salida: no es aislamiento de memoria del SO (misma limitación documentada en
  Slice2);
- un fallo indeterminado (`IndeterminateDispatchError`) deja resultado
  desconocido y requiere intervención humana; un fallo parcial
  (`PartialDispatchError`) deja el literal confirmado sin Enter. En ambos casos
  el estado no avanza y no hay recuperación automática por diseño;
- el límite de 8192 bytes UTF-8 por mensaje (`_MESSAGE_MAX_BYTES`) puede
  rechazar instrucciones largas legítimas; es un techo conservador de v1;
- una sesión tmux en un socket no por defecto (`-L`/`-S`) no es soportada;
- el recibo exige el `message` para verificar su digest (el controlador lo
  retiene). El CLI expone esto mediante `--message-file`: el archivo es texto
  UTF-8 crudo, sin recortes ni normalización, y su tamaño se acota antes de
  cargarlo por completo.

La evidencia y los riesgos residuales aceptados están en
[`adversarial-h3-slice3.md`](adversarial-h3-slice3.md). La decisión es
`proceed` para Slice3; H3 completo permanece abierto.

## Contrato H3 — Slice4

**Entradas:** contrato H2, Slice1/Slice2/Slice3 aceptados, y la
responsabilidad del controlador de realizar una inspección única tras un aviso
humano, sin convertirse en un gateway ni en un watcher. **Salidas:** aviso
humano cerrado `epistates/human-notice/v1`, frontera de inspección separada e
inyectable (`ReviewRunner` + `TmuxReviewRunner`) y evidencia portable
`epistates/review-evidence/v1`.

Slice4 es **sólo la inspección post-ejecución una vez**: no implementa gateway,
watcher, polling, automatización de señales ni aceptación. No hace commit, push
ni PR. La clasificación `OK`/`PARCIAL`/`BLOQ` y `apply_audit` quedan **fuera** de
este corte: el recibo aporta evidencia cruda (pass/fail por check + capture),
no una decisión.

Definition of Done de Slice4 (implementado):

- el aviso `human-notice/v1` contiene **sólo identidad y evento catalogado**
  (`external_completion`); sin prompt, comando, autoridad ni texto libre. Ligado
  a `task`/`run`/`attempt`, sesión y `dispatch_receipt` exacto (digest);
- el aviso sólo habilita inspección: la orquestación valida timestamps/frescura
  inyectados y estado `WAITING_EXTERNAL` antes de cualquier subprocess;
- la frontera `ReviewRunner` está **separada** del `HostRunner` y del
  `LiteralDispatcher`, es inyectable y read-only, con operaciones cerradas:
  `capture_once` (una única captura `capture-pane` acotada) y `run_check`
  (checks resueltos desde el catálogo confiable `{git_status, diff_check,
  unit_tests}`); el caller nunca aporta argv;
- el runner de producción usa executables absolutos, argv list, `shell=False`,
  `stdin=DEVNULL`, entorno mínimo construido desde cero, `timeout`/`output`
  acotados, UTF-8 estricto y errores saneados (sin stdout/stderr en mensajes);
  `capture-pane` es exactamente una llamada con `-J` (join explícito), rango
  acotado (`-S -{N}`), y el contenido **no** sale del runner (sólo digest +
  longitud);
- la orquestación `review_opencode_tmux` valida **toda la cadena**
  (task + adapter + preflight binding + dispatch receipt binding + message +
  política externa + human notice binding) antes de efectos; exige
  `WAITING_EXTERNAL`; **precalcula** transiciones `notify -> REVIEW_READY ->
  review -> REVIEWING` antes de cualquier captura o check;
- ejecuta **una sola captura** y **una sola vez cada check requerido** (orden
  determinista, resueltos desde la tarjeta vía `checks` declarados +
  `evidence.required`); el binding de `review-evidence/v1` exige **igualdad
  exacta** entre `evidence.checks` y los requeridos (sin faltantes, extras ni
  duplicados); **no reintenta** ante resultado indeterminado
  (`IndeterminateReviewError`); un check que retorna `fail` es un resultado
  válido, no un error;
- los entornos son **deterministas**: `TMPDIR=/tmp` silencia el warning de
  `confstr(_CS_DARWIN_USER_TEMP_DIR)` en macOS bajo entorno mínimo; `unit_tests`
  usa `PYTHONPATH=<worktree>/src` + `PYTHONNOUSERSITE=1` por instancia para ligar
  inequívocamente el worktree (no el checkout principal); los argv de Git
  desactivan fsmonitor (`-c core.fsmonitor=false`), config externa (env) y, para
  `diff_check`, cubren staged + unstado vía `--no-ext-diff --check HEAD --`;
- tras cada efecto, la orquestación **valida completamente** el `CaptureOutcome`
  y cada `CheckOutcome` (digest, longitudes, status, `check_id`, `capture_lines`
  en rango); un resultado inválido es `IndeterminateReviewError` sin reintento.
  Tras ensamblar la evidencia, la valida estructuralmente antes de retornar;
- el recibo `review-evidence/v1` **no** guarda stdout/stderr ni el contenido de
  la captura: sólo digests, longitudes UTF-8, estados pass/fail por check,
  binding exacto (cadena completa), `phases_confirmed == [capture_once,
  checks_once]`, `final_state == REVIEWING` y `confirms == "inspection_only"`;
- el CLI registra ambos schemas, exige binding completo y **rechaza opciones
  inaplicables** por schema (ninguna se ignora silenciosamente);
- la suite unittest termina en verde.

Decisiones de diseño de Slice4:

- **Aviso = identidad + evento, no autoridad.** El aviso cierra el ciclo humano
  sin conceder permiso de escritura. Su `event_id` es de un catálogo cerrado;
  nunca transporta texto libre, comando ni autoridad.
- **Dos frescuras inyectadas, política externa.** El aviso valida
  `notified_at` vs `dispatched_at` (`max_dispatch_age_seconds`); la revisión
  valida `reviewed_at` vs `notified_at` (`max_notice_age_seconds`). Ambas con
  política externa del controlador (igualdad exacta + re_deriva), igual que en
  Slice3, para impedir auto-amplificación.
- **Una captura, cada check una vez, sin reintento.** La inspección es
  deliberadamente única: `capture_once` exactamente una vez y `run_check`
  exactamente una vez por check requerido. Un fallo indeterminado (timeout,
  OSError, UTF-8 inválido, overflow) produce `IndeterminateReviewError` y no se
  reintenta: la duplicación silenciosa queda excluida.
- **Checks cerrados, pass/fail por exit code.** El caller aporta sólo
  `check_id` (identificador del catálogo); el argv lo construye el runner
  internamente. `git_status` pass = exit 0 (evidencia); `diff_check`
  (`git diff --no-ext-diff --check HEAD --`) cubre staged + unstado, pass = exit
  0, fail = exit 1; `unit_tests` pass = exit 0, fail = non-zero. Los checks
  requeridos **siempre** incluyen todos los `task_card.checks` además de los
  mapeos de `evidence.required`; el binding exige igualdad exacta.
- **Contenido sensible ausente del recibo.** El digest y la longitud de la
  captura y de cada check se calculan dentro del runner; el texto y los
  stdout/stderr nunca entran en `review-evidence/v1`.
- **Clasificación fuera del corte.** El recibo aporta pass/fail crudo; decidir
  `OK`/`PARCIAL`/`BLOQ` es autoridad del siguiente corte (auditoría), no de la
  inspección.

Honestidad sobre unicidad global:

- la orquestación es **stateless**: no persiste `event_id` ni estado. Bloquea
  replay sólo si el caller avanza el estado (`WAITING_EXTERNAL` ->
  `REVIEWING`) fuera de la función. Un caller que mienta y vuelva a presentar
  `WAITING_EXTERNAL` no puede detectarse aquí; la unicidad global exige
  persistir `(run_id, attempt_id, event_id, estado)` fuera.

Riesgos residuales aceptados de Slice4:

- la unicidad global del aviso depende de persistencia externa: esta función
  stateless no detecta replay si el caller no avanza el estado;
- `max_output_bytes` se aplica después de capturar la salida del proceso (no es
  aislamiento de memoria del SO); el contenido se descarta y nunca se persiste;
- un resultado indeterminado (`IndeterminateReviewError`) exige intervención
  humana y nunca se reintenta automáticamente;
- el check `unit_tests` ejecuta la suite de pruebas del worktree en un entorno
  mínimo (sin `PATH`/`HOME`/`TMUX*`): proyectos que requieran configuración de
  entorno específica podrían necesitar un adaptador posterior;
- el recibo confirma inspección técnica (captura + checks una vez), no que el
  agente comprendió ni que el resultado es aceptable; la clasificación queda
  para el siguiente corte.

## Contrato H3 — Slice5

**Entradas:** contrato H2, Slice1/Slice2/Slice3/Slice4 aceptados, y la
responsabilidad del controlador de cerrar la auditoría ligando la inspección al
audit-result exacto **antes** de aplicar una transición. **Salidas:** puente
puro `review-evidence/v1` → `audit-result/v1` → `apply_audit`
(`epistates.audit_review`), **ampliación pre-release** del `audit-result/v1`
(`review_evidence_digest` + `capture` en el catálogo de `evidence_id`), fixture
`audit-result-review-bound.json` y CLI de binding completo.

Esta es una **ampliación pre-release del contrato**, **no** "version-compatible"
ni "backward compatible": los artefactos bridge NO son aceptados por validadores
`v1` anteriores a Slice5 (rechazan `review_evidence_digest` como campo
desconocido). El validador nuevo sigue aceptando artefactos H2 puros (sin campos
bridge) por compatibilidad de lectura.

Slice5 es **sólo el cierre del puente**: no añade ejecución, automatización,
gateway, watcher, polling ni persistencia. No hace commit, push ni PR. No lanza
subprocesos, no lee el reloj, no escribe estado ni archivos. La decisión
(`classification`/`decision`/`decision_reference`), la autoridad
(`grant_id`/`grant_digest`) y el timestamp (`observed_at`) llegan como decisión
explícita inyectada por el controlador/mantenedor y se validan contra parámetros
externos esperados.

Definition of Done de Slice5 (implementado, corregido tras ronda adversarial C1):

- `validate_audit_review_binding` reutiliza los validadores existentes
  (`validate_review_evidence_binding` para la cadena completa y
  `validate_audit_binding` para tarjeta/grant/run/attempt) y añade, sin
  duplicar reglas: `review_evidence_digest` presente y coincidente, evidencia
  derivada exclusivamente desde `review-evidence`, decisión anti-auto-amplificada,
  **política externa de timestamp** y **autoridad externa inyectada**;
- la evidencia del audit-result coincide **exactamente** (identidad/status/digest
  y orden) con la derivada desde `review-evidence`: ni checks omitidos, extra ni
  reordenados; la captura queda representada mediante `evidence_id` cerrado
  (`capture`) y digest verificable;
- `classification`, `decision` y `authority_binding.decision_reference` llegan
  como decisión explícita inyectada y se validan contra los parámetros externos
  esperados; no se derivan de exit codes ni el ejecutor se autoacepta;
- **política externa de timestamp:** `observed_at` debe coincidir **exactamente**
  con `expected_observed_at` inyectado y satisfacer una ventana
  `max_audit_age_seconds` externa (finita, positiva, techo 7200s): exige
  `observed_at >= review_evidence.reviewed_at` y delta <= política. Un timestamp
  futuro autodeclarado, anterior al review o stale se rechaza; no se lee el reloj;
- **autoridad externa inyectada:** `authority_binding.grant_id`/`grant_digest`
  se validan contra `expected_grant_id`/`expected_grant_digest` externos, que a
  su vez deben coincidir con `task_card.authority`. El grant de la tarjeta es
  correlación, no autoridad actual; un JSON no puede elegir su propia autoridad;
- un review con cualquier check `fail` no puede producir `OK`/`proceed`/`DONE`;
  evidencia incompleta o misbound falla cerrado;
- **bidireccionalidad anti-downgrade:** `capture` y `review_evidence_digest` se
  requieren mutuamente en la validación estructural/schema. No se puede
  downgradear un artefacto bridge a H2 eliminando un solo campo (p. ej. sólo
  `review_evidence_digest` manteniendo `capture`);
- `apply_audit_from_review` exige `current_state == REVIEWING`, valida **todo**
  antes de `apply_audit` (cero llamadas a `apply_audit` ante fallo de timestamp,
  política o autoridad), no ejecuta subprocess, no lee reloj, no escribe estado
  ni archivos, y retorna el audit-result ligado junto con el estado derivado;
- la semántica de transiciones es exactamente la del ADR-0001
  (`OK`/`proceed`→`DONE`, `PARCIAL`/`fix-and-retry`→`CORRECTION_SENT`,
  `PARCIAL`/`escalate`→`BLOCKED`, `BLOQ`/`escalate`→`BLOCKED`); sin
  combinaciones nuevas;
- el CLI registra el modo puente del `audit-result` (detectado por
  `review_evidence_digest` presente), exige el binding completo y **rechaza**
  opciones inaplicables por schema (ninguna se ignora silenciosamente); las
  opciones de decisión y autoridad (`--review-evidence`,
  `--expected-classification`, `--expected-decision`,
  `--expected-decision-reference`, `--expected-observed-at`,
  `--max-audit-age-seconds`, `--expected-grant-id`, `--expected-grant-digest`)
  sólo aplican al audit-result en modo puente;
- la suite unittest termina en verde.

Decisiones de diseño de Slice5:

- **Ampliación pre-release, no "version-compatible".** Se añaden
  `review_evidence_digest` y `capture` al schema `audit-result/v1` como
  ampliación pre-release. El validador nuevo acepta artefactos H2 (sin campos
  bridge) y bridge (con ellos); los validadores v1 anteriores rechazan los
  bridge. No se duplican reglas entre código y schema.
- **Bidireccionalidad `capture` <-> `review_evidence_digest`.** El validador
  estructural impone que ambos campos se requieren mutuamente. Así se impide el
  downgrade: eliminar sólo `review_evidence_digest` de un artefacto bridge
  manteniendo `capture` se rechaza cerrado (antes `validate_audit_binding` +
  `apply_audit` legado producían `DONE`). Eliminar **todos** los campos bridge
  produce un artefacto H2 distinto y válido; el host H3 debe usar exclusivamente
  `apply_audit_from_review` y **no** presentar `apply_audit` legado como
  equivalente.
- **`capture` como `evidence_id` cerrado.** La captura se representa en
  `evidence[]` con `evidence_id == "capture"`, `status == "pass"` y el
  `capture_digest` de review-evidence. La regla estructural H2 (`OK` exige toda
  la evidencia en `pass`) sigue valiendo: capture es `pass` y los checks fallidos
  bloquean `OK`.
- **Match exacto de evidencia, no subconjunto.** El puente compara la evidencia
  del audit-result con la derivada desde review-evidence como una firma ordenada
  `(evidence_id, status, digest)`: así se rechazan checks omitidos, extra o
  reordenados, y captura omitida o con digest cambiado.
- **Decisión, autoridad y timestamp inyectados y anti-auto-amplificados.** El
  audit-result declara `classification`/`decision`/`decision_reference`,
  `grant_id`/`grant_digest` y `observed_at` (es portable) y debe coincidir con
  los parámetros externos inyectados por el controlador/mantenedor. Ningún valor
  autodeclarado amplía autoridad o frescura: el binding re_deriva digests y
  políticas desde la cadena, no desde el recibo. El grant de la tarjeta es
  correlación; la autoridad actual llega por parámetro externo.
- **`apply_audit` sigue siendo la autoridad de transición.** El puente valida
  todo antes y después delega en la máquina de estados pura H2; no reimplementa
  la transición.

Riesgos residuales aceptados de Slice5:

- el puente es **stateless**: no persiste la decisión ni el
  `review_evidence_digest`. Un caller que reincorpore el mismo audit-result con
  `current_state == REVIEWING` no puede detectarse aquí; la unicidad global
  exige persistir `(run_id, attempt_id, review_evidence_digest, estado)` fuera;
- el puente no atestigua la procedencia de la decisión del mantenedor: el
  binding es evidencia de correlación (audit-result ↔ review-evidence ↔ tarjeta
  ↔ grant externo), no firma criptográfica. Un host futuro deberá verificar la
  cadena de autoridad externamente;
- `review_evidence_digest` opcional permite que un audit-result H2 conviva con
  uno ligado: el binding del puente exige el campo, pero la sola presencia del
  campo no prueba que la decisión provenga del mantenedor (sólo la coincidencia
  con los parámetros externos inyectados);
- el puente confía en que el caller (controlador) inyecte honestamente
  `expected_classification`/`expected_decision`/`expected_decision_reference`/
  `expected_observed_at`/`max_audit_age_seconds`/`expected_grant_id`/
  `expected_grant_digest`: éstos no se derivan de la evidencia. La separación de
  funciones (quien audita no es quien ejecutó) es la salvaguarda organizativa, no
  una garantía del contrato;
- eliminar **todos** los campos bridge produce un artefacto H2 distinto que el
  `apply_audit` legado acepta: la bidireccionalidad estructural impide el
  downgrade de un solo campo, pero no prohíbe que un host use el camino H2. La
  convención operativa H3 es usar exclusivamente `apply_audit_from_review`.

La evidencia y los riesgos residuales aceptados están en
[`adversarial-h3-slice5.md`](adversarial-h3-slice5.md). La decisión es
`proceed` para Slice5. Con Slice1–Slice5 aceptados, H3 queda cerrado; integración
Git y preparación de release requieren autoridad separada.


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
PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m epistates validate fixtures/dispatch-receipt-ok.json \
  --task-card fixtures/task-card-valid.json \
  --adapter-capabilities fixtures/adapter-capabilities-opencode-tmux.json \
  --preflight-result fixtures/preflight-result-ok.json \
  --run-id run-001 --attempt-id attempt-001 \
  --expected-session-name epistates-opencode --expected-command idle \
  --max-preflight-age-seconds 600 \
  --message-file fixtures/dispatch-message.txt
PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m epistates validate fixtures/human-notice-ok.json \
  --task-card fixtures/task-card-valid.json \
  --adapter-capabilities fixtures/adapter-capabilities-opencode-tmux.json \
  --dispatch-receipt fixtures/dispatch-receipt-ok.json \
  --run-id run-001 --attempt-id attempt-001 \
  --expected-session-name epistates-opencode \
  --max-dispatch-age-seconds 3600
PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m epistates validate fixtures/review-evidence-ok.json \
  --task-card fixtures/task-card-valid.json \
  --adapter-capabilities fixtures/adapter-capabilities-opencode-tmux.json \
  --preflight-result fixtures/preflight-result-ok.json \
  --dispatch-receipt fixtures/dispatch-receipt-ok.json \
  --human-notice fixtures/human-notice-ok.json \
  --run-id run-001 --attempt-id attempt-001 \
  --expected-session-name epistates-opencode --expected-command idle \
  --max-preflight-age-seconds 600 --max-dispatch-age-seconds 3600 \
  --max-notice-age-seconds 3600 \
  --message-file fixtures/dispatch-message.txt
PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m epistates validate fixtures/audit-result-review-bound.json \
  --task-card fixtures/task-card-valid.json \
  --adapter-capabilities fixtures/adapter-capabilities-opencode-tmux.json \
  --preflight-result fixtures/preflight-result-ok.json \
  --dispatch-receipt fixtures/dispatch-receipt-ok.json \
  --human-notice fixtures/human-notice-ok.json \
  --review-evidence fixtures/review-evidence-ok.json \
  --run-id run-001 --attempt-id attempt-001 \
  --expected-session-name epistates-opencode --expected-command idle \
  --max-preflight-age-seconds 600 --max-dispatch-age-seconds 3600 \
  --max-notice-age-seconds 3600 \
  --message-file fixtures/dispatch-message.txt \
  --expected-classification OK --expected-decision proceed \
  --expected-decision-reference conversation-2026-08-11 \
  --expected-observed-at 2026-08-11T19:00:00Z \
  --max-audit-age-seconds 3600 \
  --expected-grant-id maintainer-e1-contracts \
  --expected-grant-digest sha256:24a39dff4b7a38f45959b89850debed2bb584fb4c887278748064ed6f1eda2cd
```
