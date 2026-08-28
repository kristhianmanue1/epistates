# PLAN EPI-E3-001 — señal local y consumo atómico

**Estado:** E3a autorizado para diseño documental; runtime bloqueado. **ADR:**
[`ADR-0004`](../architecture/0004-senal-local-y-consumo-atomico.md). Este plan
no autoriza watcher, reactivación, cambios de schemas/CLI/runtime, dependencias,
operaciones Git protegidas ni interfaces externas.

## Propósito

Preparar el contrato mínimo para que una señal local pueda reemplazar el aviso
humano sin convertirse en autorización ni en polling del controlador.

## Requisitos

- REQ-1: cada señal aceptable se liga a `task_id`, `run_id`, `attempt_id`,
  adaptador, sesión y digest del `dispatch-receipt` exacto.
- REQ-2: el consumo único sobrevive restart y falla cerrado ante concurrencia,
  dato corrupto, identidad cruzada o TTL no válido.
- REQ-3: una señal sólo habilita inspección read-only; nunca dispatch,
  corrección, aceptación ni mutación Git.
- REQ-4: el recibo minimiza datos: no guarda prompt, comando, captura, secretos
  ni texto libre.

## No objetivos

- Elegir o implementar una fuente concreta de señal.
- Crear un watcher, daemon, socket, polling o integración de red.
- Definir una API de reactivación o activar E4.
- Sustituir `human-notice/v1` o modificar contratos v1 publicados.

## Tareas

```text
TAREA EPI-E3-001-A — contrato arquitectónico de E3a
  Consumes: ADR-0004, README §8/§11, human-notice.py, project-manifest.yaml y
    docs/development-workflow.md.
  Produce: ADR aceptada, este plan y task-card/v1 vinculada.
  Steps:
  - [x] Separar recibo persistente, watcher y reactivación en E3a/E3b/E4.
  - [x] Declarar la frontera: señal aceptada sólo solicita inspección read-only.
  - [x] Registrar amenazas mínimas y condiciones de parada.
  Verificación: enlaces locales, validación de tarjeta, diff limpio y suite.

TAREA EPI-E3-001-B — diseño ejecutable del contrato de recibo
  Consume: resultado aceptado de EPI-E3-001-A y un contrato de tarea nuevo.
  Produce: propuesta de schema/API/store con semántica de crash/restart,
    concurrencia, TTL y retención; fixtures nominales y adversariales.
  Tarjeta documental: [e3a-receipt-design](2026-08-28-e3a-receipt-design.task-card.json).
  Steps:
  - [x] Proponer identidad, resultados cerrados, consumo único y matriz de
    escenarios — ver [propuesta E3a](2026-08-28-e3a-receipt-design.md).
  - [x] Implementar store SQLite y pruebas de consumo bajo la
    [task-card E3b](2026-08-28-e3b-receipt-store.task-card.json); pendiente de
    revisión adversarial fresca.
  Stop: si exige dependencia, fuente de red, credenciales, contenido libre o
    cambia task-card/v1, detener y pedir ADR/autoridad nueva.

TAREA EPI-E3-001-C — revisión adversarial de E3a
  Consume: implementación y fixtures de EPI-E3-001-B.
  Produce: dictamen independiente `proceed`, `fix-and-retry` o `escalate`.
  Debe atacar replay, doble consumo, crash/restart, TTL/reloj, identidad cruzada,
  flood, corrupción y kill switch.
  Resultado: [proceed](../adversarial-e3a-receipt-store.md) tras corregir
  colisiones, estado cruzado, replay tras restart y digest adulterado.

TAREA EPI-E3-001-D — watcher de mínimo privilegio (E3b)
  Requiere: aceptación de E3a, contrato de fuente permitido y tarea separada.
  Produce: watcher que sólo registra/consume y solicita inspección; no puede
    ejecutar efectos operativos.
```

## DoD de E3a documental

- ADR y plan distinguen persistencia de recibos, watcher y reactivación.
- Existe una `task-card/v1` que limita la tarea documental a `docs/`.
- El contrato declara identidad, atomicidad, TTL, crash/restart, concurrencia,
  minimización y resultados cerrados antes de código.
- Los enlaces locales añadidos y la tarjeta son válidos; la suite queda verde.
- Una revisión adversarial fresca será requisito de aceptación para EPI-E3-001-B
  y no se considera cumplida por esta planificación.
