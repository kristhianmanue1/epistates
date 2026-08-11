# ADR-0001 — Resultado de auditoría y máquina de estados v1

**Estado:** aceptado para implementación. **Fecha:** 2026-08-11.

## Contexto

H1 valida la intención y los límites de una tarea, pero no define cómo una
observación posterior se convierte en una decisión. El reporte del ejecutor es
dato no confiable; terminar un proceso tampoco demuestra corrección ni concede
autoridad para aceptar cambios.

## Decisión

H2 introduce dos contratos locales y puros:

1. una máquina de estados cerrada, sin persistencia ni efectos laterales;
2. `epistates/audit-result/v1`, ligado a `task_id`, `run_id`, `attempt_id`, al
   digest de la tarjeta y a la concesión de autoridad observada.

Los estados son `PREPARED`, `DISPATCHED`, `WAITING_EXTERNAL`, `REVIEW_READY`,
`REVIEWING`, `CORRECTION_SENT`, `DONE` y `BLOCKED`. `DONE` y `BLOCKED` son
terminales. Sólo estas combinaciones de auditoría producen transición:

| Clasificación | Decisión | Estado siguiente |
|---|---|---|
| `OK` | `proceed` | `DONE` |
| `PARCIAL` | `fix-and-retry` | `CORRECTION_SENT` |
| `PARCIAL` | `escalate` | `BLOCKED` |
| `BLOQ` | `escalate` | `BLOCKED` |

La evidencia se registra mediante IDs de catálogo, estado y digest; no conserva
salida libre, prompts ni secretos. `missing` exige digest nulo; `pass` o `fail`
exigen un digest SHA-256. `OK` exige que toda la evidencia sea `pass`.

Antes de una transición, el runtime calcula JSON canónico y liga exactamente
`task_card_digest` a la tarjeta y `grant_digest` a su bloque de autoridad. También
traduce `evidence.required` y todos los `checks[].check_id` de la tarjeta a IDs
que deben estar presentes en el resultado. El caller aporta además `run_id` y
`attempt_id` esperados desde su contexto vigente; copiarlos del resultado no
constituye verificación. El binding es evidencia de correlación, no
atestación: un host futuro aún deberá verificar la procedencia de la decisión
del mantenedor.

La forma canónica usa UTF-8, claves ordenadas, separadores JSON compactos y
`ensure_ascii=false`; los contratos v1 no contienen números de punto flotante.
La validación CLI de un resultado exige `--task-card`, `--run-id` y
`--attempt-id`; no permite interpretar una validación estructural aislada como
autorización de transición. El JSON Schema expresa la forma portable; el CLI es
normativo para restricciones semánticas como fechas reales, IDs de evidencia
únicos y bindings entre artefactos.

## Consecuencias

- la misma entrada produce siempre la misma transición;
- ninguna cadena autodeclarada puede crear estados o decisiones nuevos;
- el adaptador H3 tendrá que resolver checks y producir evidencia saneada;
- persistencia, CAS, firmas, sesiones y ejecución quedan fuera de H2;
- un timeout o evidencia incompleta nunca puede cerrar en `DONE`.
