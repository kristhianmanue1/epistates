# Ronda adversarial — primer prompt OpenCode E4

Fecha: 2026-08-28

Tarjeta: `e4-opencode-first-prompt`

Decisión: **BLOQUEADO para wake y para un segundo prompt.**

## Evidencia observada

- El servidor efímero autenticado escuchó sólo en `127.0.0.1:4096`.
- `GET /global/health` devolvió `200` y `GET /agent` confirmó un único
  `epistates-inspect` con `zai/glm-5.2`.
- Se creó una sesión efímera y se envió exactamente un `POST
  /session/:id/prompt_async` con el mensaje fijo; respondió `204`.
- Durante 45 segundos, `GET /session/:id/message` sólo mostró el mensaje del
  usuario. No se observó respuesta del asistente ni parte cuyo tipo contuviera
  `tool`.
- La sesión se eliminó y el servidor se detuvo al finalizar. El árbol de
  trabajo no cambió durante el ciclo.

## Ronda adversarial

| Hipótesis | Resultado | Veredicto |
| --- | --- | --- |
| Un `204` prueba que GLM ejecutó y respondió | Rechazado: sólo prueba aceptación asíncrona; no apareció mensaje del asistente antes del timeout. | No hay evidencia de inferencia completada. |
| El modelo pudo usar herramientas mientras esperaba | No se observó ninguna parte `tool` y la configuración efectiva mantiene `* -> deny`. | Sin evidencia de efecto, pero no equivale a una respuesta validada. |
| El cierre del servidor puede ocultar una respuesta tardía | Confirmado: al expirar el límite, el cleanup eliminó sesión y detuvo el proceso. | No reintentar sin nueva tarjeta/autoridad. |
| El prompt se transformó en wake automático | Rechazado: no hubo recibo E3, `WakeGuardStore`, watcher ni llamada posterior. | Sigue prohibido. |
| Credencial o listener quedó persistente | Rechazado: contraseña aleatoria sólo fue de proceso y el servidor se cerró. | Sin exposición persistente observada. |

## Conclusión y siguiente decisión

El experimento prueba el contrato HTTP hasta el acuse `204`, pero no una
respuesta GLM. Una nueva autorización debe decidir entre: (a) una segunda
prueba con un límite de espera mayor y diagnóstico de estado del proveedor, o
(b) investigar primero la autenticación/configuración de Z.ai sin enviar otro
prompt. Ninguna opción autoriza wake, automatización, cambios de permisos,
credenciales persistentes, commit o publicación.
