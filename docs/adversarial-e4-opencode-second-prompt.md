# Ronda adversarial — segundo prompt OpenCode E4

Fecha: 2026-08-28

Tarjeta: `e4-opencode-second-prompt`

Decisión: **BLOQUEADO para wake y para un tercer prompt.**

## Evidencia observada

- El preflight confirmó `health=200`, el agente `zai/glm-5.2` y `zai` en
  `connected`.
- Se creó una sesión efímera y exactamente un `prompt_async` respondió `204`.
- La lectura de mensajes mostró un registro `assistant`, pero no contenía
  partes, texto ni error declarado. No se observó una parte `tool`.
- El árbol de trabajo no cambió durante el ciclo; la sesión se eliminó y el
  servidor se detuvo.

## Hallazgo adversarial principal

El criterio de espera consideró suficiente que existiera un mensaje con
`role=assistant`. La evidencia mostró que OpenCode puede publicar primero un
marcador de asistente sin partes, por lo que ese criterio es insuficiente para
demostrar respuesta o finalización. El cleanup cerró la sesión justo después de
ese marcador. En consecuencia, este experimento no prueba una respuesta GLM
completa, aunque el proveedor ya apareciera conectado.

## Ronda adversarial

| Hipótesis | Resultado | Veredicto |
| --- | --- | --- |
| `zai_connected` garantiza una respuesta útil | Rechazado: se observó sólo un marcador vacío. | Conectividad no equivale a finalización. |
| Un mensaje `assistant` prueba inferencia terminada | Rechazado: no tenía partes ni texto. | Control de espera defectuoso. |
| El modelo ejecutó herramientas | No se observó parte `tool`; la política sigue `* -> deny`. | Sin efecto observado, no prueba de respuesta. |
| Se puede reabrir la misma sesión para esperar | Rechazado: fue eliminada según el contrato de cleanup. | Requiere una nueva sesión y autoridad. |
| El fallo autoriza wake | Rechazado: no participaron recibos E3, guard, watcher ni automatización. | Wake bloqueado. |

## Requisito para una nueva prueba

Una tercera tarjeta debe corregir el preflight: esperar una condición final
explícita, por ejemplo una parte de texto no vacía o un estado terminal de
sesión documentado, y no tratar la mera existencia de un registro assistant
como respuesta. Debe conservar el límite de un solo prompt, herramientas
denegadas, servidor loopback, timeout explícito y cleanup posterior. Requiere
autorización nueva del mantenedor.
