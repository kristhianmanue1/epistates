# ADR-0002 — Adopción limitada de prácticas Skevi

**Estado:** aceptado para documentación de proceso. **Fecha:** 2026-08-28. **Plan:**
[`EPI-SKEVI-001`](../plans/2026-08-28-adopcion-practicas-skevi.md).

## Contexto

Epistates ya opera mediante contratos explícitos, evidencia separada de la
autoridad y rondas adversariales. El análisis comparativo con Skevi identificó
prácticas que pueden hacer más verificable el trabajo de diseño y documentación:
clasificación de tareas por disparadores observables, planes de escala con una
sola fuente de DoD, separación de documentos por vida útil y resultados por
línea de evidencia.

Esas prácticas no son contratos de Epistates ni concesiones de autoridad. Una
adopción literal crearía riesgos concretos: duplicar `task-card/v1`, transformar
un gate estructural en señal de corrección o autorización, y reescribir la
evidencia histórica de H1–H4 para ajustarla a una taxonomía nueva.

La verificación local de AN-KLA es íntegra, aunque `context status` informa
`context_target_changed_outside_managed_block`. La inspección muestra que el
manifest local conserva un `target_sha256` distinto del `AGENTS.md` observado,
sin diagnósticos de bloque o contrato administrado. Este ADR no adopta esa
baseline ni modifica instrucciones administradas; cualquier acción sobre ella
requiere su flujo específico y autoridad separada.

## Decisión

Adoptar Skevi únicamente como fuente de prácticas de proceso, bajo estas reglas:

1. `task-card/v1` continúa siendo la única tarjeta de trabajo canónica. Una
   guía puede explicar cómo prepararla, pero no crear campos, grants ni una
   representación paralela. Un cambio de contrato exige una ADR y versión
   separadas.
2. Los cambios nuevos se clasifican con disparadores observables. La clase y el
   DoD se fijan en el contrato de la tarea; si aparece una frontera pública,
   runtime, schema o coordinación multi-tarea, se eleva el rigor en vez de
   reducirlo por conveniencia.
3. Los planes existen sólo para coordinación de varias tareas. El plan posee
   pasos y DoD; cada tarea lo referencia sin duplicar criterios de aceptación.
4. La nueva documentación distinguirá decisión vigente, plan ejecutable y
   evidencia histórica. Los artefactos H1–H4 existentes no se mueven ni
   reescriben bajo esta decisión; una migración futura requerirá alcance y
   verificación propios.
5. Los reportes nuevos podrán declarar `pass`, `fail` o `inconclusive` por
   línea de evidencia, separado del estado global `OK`, `PARCIAL` o `BLOQ`.
   Una línea `inconclusive` nunca cerrará un gate.
6. Un gate de planes, si se propone, será opt-in, aislado del runtime y probado
   contra planes reales y casos adversariales. Verificará estructura, no
   autoridad, aceptación humana ni corrección semántica.

Esta ADR no acepta por sí misma ninguna tarea posterior ni autoriza cambios de
runtime, schemas, CLI, adaptadores, commits, publicaciones o instrucciones
AN-KLA.

## Alternativas descartadas

- **Copiar Skevi completo:** acoplaría la estructura y herramientas de otro
  proyecto a Epistates, sin demostrar que sus hogares o gates resuelvan una
  necesidad local.
- **Crear una plantilla de tarea adicional:** duplicaría `task-card/v1` y
  permitiría que contrato, evidencia y autoridad deriven por separado.
- **Reorganizar de inmediato toda la documentación:** dañaría enlaces y el
  valor probatorio de los cierres H1–H4 sin un beneficio verificable inicial.
- **Instalar un gate de planes antes de contar con un plan real:** produciría
  una señal potencialmente vacua y no evidencia de que el gate detecta fallos.

## Consecuencias

- La iniciativa se implementa por tareas del plan EPI-SKEVI-001, con revisión
  adversarial fresca antes de aceptar hitos.
- Las tareas posteriores pueden crear documentación e índices dentro del plan,
  pero no alterar contratos públicos ni aceptar una ADR posterior sin decisión
  del mantenedor.
- El aviso AN-KLA queda registrado como riesgo de contexto; no es prueba de
  corrupción porque `verify` terminó correctamente, pero impide tratar la
  baseline local como confirmada hasta que se resuelva mediante el flujo
  autorizado.
