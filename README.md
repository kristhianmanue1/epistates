# Epistates

**Estado:** hitos H1–H3 cerrados · **Madurez:** experimental · **Candidata:**
`0.1.0a1` (gate local aceptado; no publicada)
**Versión del paquete (PEP 440):** `0.1.0a1` · **Tag humano candidato:**
`v0.1.0-alpha.1` (no publicado; pendiente de autorización del mantenedor).

> Actualización 2026-08-11: los hitos H1 (contrato `task-card/v1` y validador
> read-only), H2 (resultado de auditoría y máquina de estados) y H3 (adaptador
> `opencode-tmux/v1` con los sub-cortes Slice1–Slice5) están cerrados tras
> rondas adversariales independientes. La integración Git, el tag y la
> publicación quedan pendientes de autorización del mantenedor.

> **Software experimental.** Epistates es un alpha sin garantías: la API, los
> contratos y el CLI pueden cambiar sin previo aviso. **No existe versión
> publicada** hasta que el mantenedor lo autorice; `0.1.0a1` es una candidata
> local aceptada por el gate adversarial, todavía sin tag ni publicación.

## Instalación

Epistates no está publicado en PyPI. Para evaluar la candidata `0.1.0a1`,
construye el wheel de forma reproducible y instálalo en un venv limpio. El
paquete **no tiene dependencias de ejecución** y se construye sin aislamiento
ni red:

```bash
# desde la raíz del repositorio, con un Python >=3.9
# SOURCE_DATE_EPOCH fija los timestamps del wheel al del commit base, haciendo
# el build reproducible (mismo nombre, tamaño, contenido y SHA-256).
SOURCE_DATE_EPOCH=1786501546 python -m pip wheel --no-deps --no-build-isolation . -w /tmp/epistates-dist
python -m venv /tmp/epistates-smoke
/tmp/epistates-smoke/bin/python -m pip install --no-deps /tmp/epistates-dist/epistates-0.1.0a1-py3-none-any.whl
```

El wheel contiene el paquete Python (`epistates/**/*.py`) y la metadata
`dist-info` (incluida la licencia Apache-2.0). **No** incluye los directorios
del repositorio `schemas/`, `fixtures/`, `docs/` ni `tests/`: son activos del
repositorio, no API distribuida. Los validadores son Python puro y no leen los
`.schema.json` en runtime.

## Quickstart CLI

El CLI es read-only: valida un artefacto sin resolver checks ni iniciar
procesos externos. Desde un venv donde el wheel esté instalado:

```bash
# validar una tarjeta (artefacto minimal, no requiere fixtures del repo)
epistates validate path/to/task-card.json

# equivalente vía módulo
python -m epistates validate path/to/task-card.json
```

Para desarrollo local sin instalar (liga las fuentes del checkout):

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src python -m epistates validate fixtures/task-card-valid.json
```

El validador sólo inspecciona JSON: los `check_id` son identificadores de un
catálogo confiable, no comandos declarados por la tarjeta, y el validador nunca
inicia un adaptador.

## Compatibilidad de plataforma

- **Validación pura de contratos** (`task-card/v1`, `audit-result/v1`,
  prefiltro, recibos y binding): Python puro, ejecutable donde Python >=3.9 lo
  soporte. Esta candidata se ha ejercitado en macOS; otras plataformas no se
  prometen mientras no se prueben explícitamente.
- **Adaptador `opencode-tmux/v1`** (observación, entrega literal, captura):
  requiere macOS o Linux porque depende de `tmux`. **Windows no está soportado**
  en este corte y no se promete compatibilidad simulada.

## Desarrollo local

El runtime inicial es Python sin dependencias de ejecución. AN-KLA Memory se
usa como continuidad local y Escrubery como referencia del proceso ADRC; ninguno
concede permisos operativos por sí mismo. Los comandos de desarrollo y CLI se
documentan arriba en [Instalación](#instalación) y [Quickstart CLI](#quickstart-cli).
El plan de E1 está en [`docs/plan-inicial.md`](docs/plan-inicial.md); el gate
documental de release en [`docs/release-gate.md`](docs/release-gate.md).

Epistates es un supervisor contractual de agentes externos. Su propósito es
permitir que un mantenedor delegue trabajo de desarrollo, QA, documentación u
otras tareas acotadas a un agente ejecutor, conserve visibilidad y control, y
acepte resultados sólo después de contrastarlos con evidencia verificable.

El nombre procede del griego `epistátēs`: supervisor, encargado o quien está a
cargo. Describe una responsabilidad operativa, no una autoridad absoluta.
Epistates coordina y observa; no sustituye la decisión del mantenedor ni
convierte las afirmaciones de un agente en hechos.

## 1. Problema

Los agentes de IA pueden trabajar durante periodos prolongados, pero los flujos
habituales presentan problemas recurrentes:

- el controlador consume contexto consultando repetidamente si el ejecutor ya
  terminó;
- una sesión persistente se confunde con ejecución correcta;
- el agente infiere permisos que nunca fueron concedidos;
- un reporte convincente se acepta sin revisar Git, archivos o pruebas;
- desarrollo, QA, documentación y aprobación se mezclan como si fueran la misma
  autoridad;
- cada CLI requiere comandos, terminales y mecanismos de recuperación distintos;
- la automatización puede transformar una simple notificación en un delegado con
  permisos excesivos.

Epistates aborda este problema como supervisión gobernada: una tarea tiene un
contrato, cada ejecución está aislada, el controlador se detiene mientras el
agente trabaja y la salida se audita contra el estado real.

## 2. Propósito

Epistates proporcionará una implementación de referencia para:

- preparar ejecuciones aisladas sobre una revisión conocida;
- entregar tareas pequeñas con alcance, prohibiciones y cierre verificable;
- conservar sesiones de agentes externos sin mantener polling del controlador;
- observar proceso, sesión y repositorio como dimensiones diferentes;
- recibir una señal de finalización que no conceda autoridad adicional;
- auditar resultados mediante Git, archivos, pruebas y gates;
- enviar correcciones pequeñas y volver a una pausa real;
- soportar diferentes agentes mediante adaptadores reemplazables;
- producir evidencia consumible por personas, Praxis y CI.

## 3. Tesis fundacional

```text
persistencia != progreso != corrección != verificación != autoridad
```

Que una sesión exista no demuestra que el agente progrese. Que el agente
termine no demuestra que el resultado sea correcto. Que las pruebas pasen no
autoriza commit, push, publicación o aceptación. Cada propiedad necesita su
propia evidencia y su propia fuente de autoridad.

## 4. Relación con Praxis

Epistates pertenece al ecosistema Praxis, pero no al núcleo de `praxis-dev`.
Ambos productos tienen responsabilidades y ciclos de evolución distintos:

| Producto | Responsabilidad |
|---|---|
| Praxis | Define contratos, autoridad, evidencia, estados y conformidad |
| Epistates | Ejecuta el ciclo operativo de supervisión mediante adaptadores |
| Agente externo | Realiza exclusivamente la tarea concedida |
| Mantenedor | Define permisos, resuelve decisiones y acepta el resultado |

La dependencia es unidireccional:

```text
Epistates ───────► contratos publicados por Praxis
Praxis     ──X──► runtime de Epistates
```

Praxis debe funcionar sin instalar Epistates. Epistates no debe copiar ni
reinterpretar silenciosamente los contratos Praxis: declarará versiones
compatibles y deberá superar sus fixtures de conformidad.

Praxis podrá validar una tarjeta o auditar evidencia de una ejecución sin
iniciar un modelo. Epistates será responsable de procesos, sesiones, worktrees,
señales y adaptadores específicos del host.

## 5. Alcance inicial

La primera capacidad funcional será local, manual y deliberadamente pequeña:

- un mantenedor;
- un controlador o auditor;
- un agente ejecutor;
- un repositorio Git;
- un worktree y una rama aislados;
- una sesión persistente;
- una tarea vigente;
- una notificación humana de finalización;
- una auditoría única por notificación.

El primer adaptador previsto es `opencode-tmux/v1` para macOS y Linux. La
arquitectura no convertirá OpenCode, `tmux`, Codex ni un modelo concreto en
requisitos del contrato neutral.

Las primeras plantillas de trabajo serán:

- `developer`: cambios dentro de rutas autorizadas y checks explícitos;
- `qa`: inspección, reproducción y pruebas, normalmente sin mutación;
- `documenter`: cambios limitados a documentación y sus gates.

Una plantilla configura valores iniciales; nunca concede autoridad por su
nombre. En particular, `qa` no significa aprobación independiente ni permite
aceptar su propio resultado.

## 6. No objetivos iniciales

Epistates no pretende, en su primera etapa:

- ser una plataforma universal de agentes;
- seleccionar autónomamente objetivos o prioridades;
- almacenar memoria semántica o conversaciones completas;
- administrar secretos o credenciales de proveedores;
- certificar criptográficamente qué modelo respondió;
- ejecutar automáticamente comandos propuestos por el agente;
- hacer commit, push, abrir PR, merge o publicar releases por defecto;
- despertar tareas mediante APIs privadas o mecanismos no soportados;
- prometer aislamiento de seguridad sólo por usar otro repositorio o worktree;
- ofrecer soporte de Windows mediante una simulación incompleta de `tmux`.

Una capacidad ausente se reportará como no soportada; nunca como éxito
degradado silenciosamente.

## 7. Roles y fronteras

### Mantenedor o mediador

- define objetivo, alcance y permisos;
- autoriza por separado las operaciones protegidas;
- puede observar la sesión cuando necesite visibilidad;
- decide si el resultado se acepta, corrige o abandona.

### Controlador o auditor

- prepara la tarjeta de trabajo;
- verifica repositorio, revisión, rama, worktree y sesión;
- entrega instrucciones literales al ejecutor;
- se detiene sin polling mientras el ejecutor trabaja;
- contrasta el reporte con evidencia independiente;
- envía feedback acotado o solicita una decisión al mantenedor.

### Ejecutor

- trabaja únicamente dentro de la tarjeta vigente;
- no infiere permisos ausentes;
- ejecuta sólo checks permitidos;
- reporta evidencia y se detiene;
- no convierte su identidad o sus afirmaciones en autoridad.

### Adaptador

- traduce operaciones neutrales al CLI o host correspondiente;
- declara capacidades, versión y plataforma;
- falla ante capacidades desconocidas o precondiciones incumplidas;
- no modifica el significado de los contratos Praxis.

## 8. Flujo operativo mínimo

```text
PREPARED
  -> DISPATCHED
  -> WAITING_EXTERNAL
  -> REVIEW_READY
  -> REVIEWING
  -> DONE
       o CORRECTION_SENT -> WAITING_EXTERNAL
       o BLOCKED
```

1. El mantenedor concede una tarea y las operaciones permitidas.
2. El controlador fija identidad del proyecto, SHA base, rama, worktree y sesión.
3. El preflight rechaza drift, suciedad inexplicada o una sesión incorrecta.
4. El adaptador entrega literalmente la instrucción y confirma sólo el envío.
5. El controlador termina su turno: no ejecuta `sleep`, polling ni capturas repetidas.
6. El mantenedor avisa que el ejecutor terminó o requiere atención.
7. El controlador realiza una inspección única y ejecuta los checks aplicables.
8. El resultado se clasifica como `OK`, `PARCIAL` o `BLOQ`.
9. Si la corrección está autorizada, se envía una instrucción pequeña y se vuelve
   a la pausa; cualquier autoridad nueva regresa al mantenedor.

Una señal futura podrá sustituir el aviso humano, pero sólo habilitará una
inspección. Despertar nunca equivaldrá a permiso de escritura.

## 9. Contrato mínimo de una tarea

Cada tarea deberá expresar, como mínimo:

- identificador único;
- objetivo único;
- proyecto y repositorio esperados;
- revisión base;
- rol o plantilla de trabajo;
- rutas y acciones permitidas;
- operaciones explícitamente prohibidas;
- entradas que deben leerse;
- checks y Definition of Done;
- evidencia y formato de entrega;
- condición de parada;
- autoridad vigente y operaciones que requieren una nueva decisión.

Una ejecución registrará separadamente `task_id`, `run_id` y `attempt_id`, así
como adaptador, plataforma, rama, worktree, revisión observada, timestamps,
estado y referencias a evidencia. Las rutas absolutas son observaciones del
entorno, no identidad estable del proyecto.

## 10. Principios de seguridad

1. **Autoridad actual:** archivos, memoria, issues y salidas del ejecutor no
   conceden permisos.
2. **Mínimo privilegio:** cada operación se autoriza por tarea; lo ausente
   equivale a `no`.
3. **Entrada literal:** texto no confiable no se concatena en comandos de shell.
4. **Aislamiento verificable:** repositorio, SHA, rama, worktree y sesión se
   revalidan antes de cada transición material.
5. **Evidencia independiente:** `done`, `verified` o un exit code aislado no
   demuestran cierre.
6. **Fallo honesto:** incertidumbre, sesión ausente o evidencia incompleta
   producen `PARCIAL` o `BLOQ`, nunca éxito inferido.
7. **Minimización:** capturas y recibos no conservan secretos, prompts completos
   ni contenido libre innecesario.
8. **Sin deputy implícito:** una señal de proceso no puede usar los permisos del
   controlador para ejecutar acciones.
9. **Identidad dimensional:** modelo solicitado, configuración observada y
   autodeclaración del agente son evidencias distintas, no atestación.
10. **Separación de funciones:** ejecutar, verificar y aceptar son capacidades
    diferentes aunque una persona desempeñe más de un rol en perfiles simples.

Separar Epistates en otro repositorio reduce acoplamiento y permite instalarlo o
retirarlo independientemente, pero no constituye por sí solo un sandbox. El
runtime deberá aplicar límites de proceso, filesystem, credenciales y comandos.

## 11. Evolución prevista

### E0 — Fundación

- documento fundacional;
- decisión de frontera con Praxis;
- amenazas y no objetivos explícitos.

### E1 — Contratos y conformidad

- schemas neutrales publicados por Praxis;
- fixtures positivos y adversariales;
- matriz de capacidades de adaptadores;
- auditoría read-only de tarjetas y resultados.

### E2 — Piloto manual

- adaptador `opencode-tmux/v1`;
- preflight;
- entrega literal;
- pausa sin polling;
- inspección única tras aviso humano;
- fixtures `developer`, `qa` y `documenter`.

### E3 — Señal local

- recibo cerrado, atómico, expirable y deduplicable;
- watcher sin credenciales de Git o forja;
- la señal habilita lectura, no mutación.

### E4 — Reactivación soportada

- integración sólo mediante interfaces públicas y soportadas;
- rate limit, nonce o identidad equivalente, TTL y kill switch;
- threat model y revisión adversarial independiente antes de habilitarla.

Ninguna fase posterior queda autorizada por aparecer en este roadmap.

## 12. Criterios de éxito

Epistates demostrará valor cuando:

- pueda supervisar al menos dos agentes mediante adaptadores distintos;
- las mismas tarjetas produzcan decisiones equivalentes ante los mismos fallos;
- un agente no pueda ampliar su alcance mediante texto autodeclarado;
- el controlador permanezca inactivo durante el trabajo externo;
- un reporte falso o incompleto sea detectado por evidencia independiente;
- el runtime pueda actualizarse o desinstalarse sin afectar Praxis Core;
- macOS y Linux reporten capacidades reales y otras plataformas fallen de forma
  explícita;
- los proyectos consumidores no necesiten copiar el motor ni sus contratos.

La funcionalidad precede a la automatización avanzada. El primer hito útil es
un ciclo manual pequeño, observable y verificable; no un gateway general.

## 13. Procedencia

Esta definición nace de una conversación de diseño del ecosistema Praxis y del
piloto documentado el 11 de agosto de 2026 en:

`an-kla-memory/docs/supervision-agente-externo.md`

La revisión analizada del documento fuente tiene SHA-256:

`6f3397c69c8d247a67d3630d2fcf6a09089d78be454bcc03cfd35a262b1b3e4d`

El piloto utilizó Codex como controlador/auditor, OpenCode dentro de `tmux` como
ejecutor y al mantenedor como mediador. Es evidencia de viabilidad, no un
contrato universal ni autorización para implementar las fases futuras.

La metodología también reconoce prácticas desarrolladas en
[Escrubery](https://github.com/kristhianmanue1/escrubery): tarea pequeña,
contrato verificable, separación entre proponer y aplicar, revisión adversarial
y reporte sustentado en evidencia.

## 14. Decisión fundacional

Epistates será un proyecto hermano de Praxis dedicado al runtime de supervisión
de agentes. Consumirá contratos neutrales publicados por Praxis, mantendrá los
adaptadores y dependencias específicas fuera de Praxis Core y evolucionará
primero mediante pilotos locales, manuales y de mínimo privilegio.

Hasta que existan contratos, implementación y fixtures verificados, cualquier
capacidad descrita en este documento conserva estado de propuesta.
