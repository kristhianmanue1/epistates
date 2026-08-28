# PLAN EPI-SKEVI-001 — adopción limitada de prácticas de diseño y desarrollo

**Estado:** cerrado con revisión adversarial `proceed` el 2026-08-28; véase
[`adversarial-epi-skevi-001.md`](../adversarial-epi-skevi-001.md). Este plan no
autoriza cambios de runtime, contratos
publicados, operaciones Git protegidas ni activación de adaptadores.

## Propósito

Incorporar prácticas verificables de diseño, arquitectura, desarrollo y
documentación inspiradas en Skevi, sin convertir Skevi en dependencia, sin
duplicar `task-card/v1` y sin reinterpretar la autoridad de Epistates.

## Resultado observable

Una persona que prepare trabajo arquitectónico en Epistates podrá encontrar un
hogar documental estable, clasificar el trabajo por disparadores observables y
relacionar objetivo, contrato, prueba y evidencia sin alterar los artefactos de
cierre H1–H4.

## Requisitos y no objetivos

- REQ-1 [restricción] [fuente: mantenedor, 2026-08-28]: conservar
  `task-card/v1` como contrato canónico; no crear una tarjeta paralela.
- REQ-2 [funcional] [fuente: análisis comparativo Skevi/Epistates,
  2026-08-28]: los documentos nuevos deben distinguir decisión vigente, plan
  ejecutable y evidencia histórica.
- REQ-3 [restricción] [fuente: AGENTS.md]: cada tarea material declara un DoD
  ejecutable y las tareas de hito reciben una ronda adversarial fresca.
- REQ-4 [restricción] [fuente: ronda adversarial, 2026-08-28]: ningún gate
  documental se interpreta como evidencia de autoridad, corrección semántica o
  aceptación humana.

No objetivos:

- No se modifica el runtime, schemas, CLI ni la semántica de contratos v1.
- No se mueve ni reescribe evidencia histórica de H1–H4 en esta iniciativa.
- No se copia Skevi ni se añade como dependencia de ejecución o desarrollo.
- No se crean commits, ramas, worktrees, sesiones, PRs, tags ni publicaciones
  fuera de una autorización explícita del mantenedor.

## Riesgos y paradas

- Si el aviso AN-KLA `context_target_changed_outside_managed_block` impide
  verificar el contexto, se detiene y se diagnostica sin reparar ni reinstalar
  instrucciones automáticamente.
- Si una mejora exige nuevos campos en `task-card/v1`, se detiene: requiere
  ADR y contrato versionado separados.
- Si un documento histórico necesita moverse para cumplir el diseño, se
  detiene: el alcance inicial sólo admite índices o documentos nuevos.
- Si una tarea requiere más de una decisión de mantenedor o toca runtime,
  schema o interfaz pública, se reclasifica y recibe un contrato propio.

## TAREAS

```text
TAREA EPI-SKEVI-001-A
  Consumes: `AGENTS.md`, `AN-KLA.md`, `docs/plan-inicial.md`, el estado Git y
    el análisis adversarial vigente.
  Produce: decisión de adopción limitada que declare alcance, no objetivos,
    compatibilidad con `task-card/v1` y el tratamiento del aviso AN-KLA.
  Steps:
  - [x] Inventariar los hogares documentales y los enlaces entrantes a artefactos de cierre — verificación: `rg -n 'plan-inicial|adversarial-h[1-4]|architecture/0001' README.md docs AGENTS.md`
  - [x] Redactar una ADR nueva sin modificar los documentos históricos — verificación: `git diff --check` y lectura completa del diff
  - [x] Contrastar que la ADR no conceda autoridad ni cambie contratos — verificación: `rg -n 'task-card/v1|autoriza|autoridad|schema' docs/architecture`

TAREA EPI-SKEVI-001-B
  Consumes: la ADR aceptada de EPI-SKEVI-001-A y `docs/plan-inicial.md`.
  Produce: índice o convención para documentos nuevos de arquitectura, planes y
    evidencia histórica, con rutas estables y sin migración retrospectiva.
  Steps:
  - [x] Definir el hogar de documentos nuevos y su propósito — verificación: cada ruta nueva existe bajo `docs/` y está enlazada desde un índice canónico
  - [x] Registrar la política de inmutabilidad de evidencia H1-H4 — verificación: `rg -n 'no.*mueve|hist.rica|H1.H4' docs`
  - [x] Comprobar enlaces Markdown locales añadidos — verificación: `python3 scripts/check_documentation_links.py docs/README.md docs/architecture/README.md docs/plans/README.md`

TAREA EPI-SKEVI-001-C
  Consumes: la ADR aceptada de EPI-SKEVI-001-A, los contratos publicados y
    `docs/agent-integration.md`.
  Produce: guía de preparación de tarea que relacione requisito, contrato,
    prueba y evidencia, usando `task-card/v1` como única tarjeta.
  Steps:
  - [x] Definir clasificación por disparadores observables y regla de escalamiento — verificación: ejemplos Bounded y Architectural con resultado no ambiguo
  - [x] Añadir formato de evidencia por línea `pass|fail|inconclusive`, separado de `OK|PARCIAL|BLOQ` — verificación: `rg -n 'pass|fail|inconclusive|OK|PARCIAL|BLOQ' docs/development-workflow.md`
  - [x] Revisar que la guía no invente campos de schema ni nuevos grants — verificación: comparación literal contra `schemas/task-card-v1.schema.json` o su recurso canónico empaquetado

TAREA EPI-SKEVI-001-D
  Consumes: resultados aceptados de EPI-SKEVI-001-A a EPI-SKEVI-001-C y al
    menos un plan ejecutable real.
  Produce: decisión sobre un gate estructural opt-in para planes, aislado del
    runtime y con límites explícitos de garantía.
  Steps:
  - [x] Evaluar un gate contra un plan real, no un corpus vacío — verificación: `check_plans.py` de Skevi devolvió `BLOQ` por falsos positivos sobre comandos entre acentos y un recurso empaquetado; el resultado respalda no adoptarlo
  - [x] Asegurar que el gate no lee secretos, no ejecuta el proyecto ni concede autoridad — verificación: no se copió ni activó un gate; ADR-0003 limita explícitamente cualquier propuesta futura
  - [x] Decidir activación o descarte mediante ADR — verificación: ADR-0003 enumera alternativas, consecuencias y límites de la señal del gate
```

## DoD del plan

- Cada tarea conserva un único contrato de tarea; no existe plantilla que
  duplique `task-card/v1`.
- Todo documento nuevo está enlazado desde un índice canónico y no rompe enlaces
  locales verificados.
- Cada cambio de comportamiento documental tiene evidencia focal y la suite de
  Epistates se ejecuta con el intérprete disponible; una restricción del sandbox
  se reporta como `inconclusive`, no como verde.
- Las tareas que toquen una frontera pública, runtime o contratos se someten a
  ADR, pruebas focales y revisión adversarial fresca antes de integrarse.
- La revisión final declara `proceed`, `fix-and-retry` o `escalate`, junto con
  riesgos residuales explícitos.

## Evidencia de partida

- `python3 -m an_kla --project-root . verify` → revisión 0 íntegra [pass].
- `python3 -m an_kla --project-root . context status` → aviso
  `context_target_changed_outside_managed_block` [inconclusive: requiere
  diagnóstico separado].
- `python3 scripts/check_sizes.py` y `python3 scripts/check_plans.py` en Skevi
  → gates estructurales verdes [pass].
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` fuera
  del sandbox → 796 pruebas en verde y una omitida [pass].
