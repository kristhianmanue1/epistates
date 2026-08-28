# ADR-0004 — Señal local y consumo atómico para E3

**Estado:** aceptado. **Fecha:** 2026-08-28. **Plan:**
[`EPI-E3-001`](../plans/2026-08-28-e3-senal-local.md).

## Contexto

Epistates alcanza `WAITING_EXTERNAL` después de un dispatch confirmado. El
contrato vigente `human-notice/v1` liga una señal humana a la tarjeta,
adaptador y `dispatch-receipt` exactos, y limita su frescura. Sin embargo, es
intencionalmente stateless: no persiste `(run_id, attempt_id, event_id, estado)`
y por sí solo no puede detectar un replay global después de reiniciar el
caller.

E3 pretende sustituir el aviso humano por una señal local. Esa señal no puede
convertirse en un deputy del controlador: su recepción no demuestra que el
agente terminó, que el resultado es correcto ni que exista autoridad para
escribir, aceptar, corregir o publicar.

## Decisión

E3 se descompone antes de implementar runtime:

1. **E3a — contrato de recibo y consumo.** Definir una semántica local,
   persistente y atómica para aceptar una señal una sola vez por contexto de
   ejecución. El recibo se liga al `dispatch-receipt` exacto y conserva sólo
   identidad, digests, clase de evento, TTL y resultado cerrado.
2. **E3b — watcher de mínimo privilegio.** Sólo podrá leer una fuente que el
   mantenedor haya permitido y solicitar la inspección única de una señal ya
   consumida. Puede persistir el recibo en su store local; no puede llamar a
   Git, `tmux`, dispatch, corrección, aceptación ni APIs privadas.
3. **E4 — reactivación.** Sólo podrá habilitar una inspección read-only mediante
   una interfaz pública y soportada. Exige rate limit, kill switch, threat model
   completo y revisión adversarial independiente antes de activarse.

El protocolo E3a deberá fijar, antes de código: identidad de señal, fuente
permitida, semántica de atomicidad y crash/restart, reloj/TTL, concurrencia,
retención y borrado. Sus resultados cerrados serán `accepted`, `duplicate`,
`expired`, `invalid` o `disabled`.

## Frontera de autoridad

Una señal aceptada sólo permite solicitar una inspección. La inspección mantiene
la cadena actual de validación y puede terminar en `OK`, `PARCIAL` o `BLOQ`; no
concede operaciones nuevas. Cualquier dispatch de corrección, mutación Git,
aceptación o publicación exige la autoridad vigente separada que ya requieren
los contratos del proyecto.

## Threat model mínimo para E3a

El diseño deberá tratar como entradas no confiables a la fuente de señal,
identidad, timestamps y estado persistido. Como mínimo debe cubrir: replay antes
y después de restart, doble consumo concurrente, señal ligada a otra tarea o
sesión, TTL inválido o reloj regresivo, flood de eventos distintos, corrupción
del store y activación del kill switch entre recepción y acción.

No se decide aún que la fuente sea sin red: el requisito vigente sólo prohíbe
credenciales de Git o de forja. Si una fuente necesitara red, credenciales,
contenido libre o una API privada, la iniciativa se detiene y requiere una ADR
posterior.

## Consecuencias

- El actual `human-notice/v1` permanece compatible y es el fallback manual.
- E3a no añade schema, CLI, daemon, watcher ni dependencia.
- Una tarea futura de runtime deberá incluir fixtures nominales y adversariales
  de concurrencia, replay, crash/restart, TTL, identidad cruzada y kill switch.
- El store de recibos es estado operativo local; no es memoria semántica AN-KLA
  ni una fuente de autoridad.

## Alternativas descartadas

- **Activar un watcher directamente:** deja indefinidos persistencia,
  deduplicación y recuperación tras fallo.
- **Usar sólo `human-notice/v1`:** no resuelve la unicidad global fuera del
  caller.
- **Reactivar a partir de la señal:** viola mínimo privilegio y mezcla señal,
  inspección y autorización.
- **Exigir red cero desde ahora:** impondría una restricción no aprobada por el
  manifiesto sin haber elegido fuente de señal.
