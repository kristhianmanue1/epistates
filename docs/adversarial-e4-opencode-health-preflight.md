# Ronda adversarial — preflight HTTP health-only OpenCode E4-L

Fecha: 2026-08-28

Tarjeta: `e4-opencode-health-preflight`

Decisión: **PROCEED para cerrar E4-L health-only; NO PROCEED para wake o
activación runtime.**

## Alcance y evidencia esperada

- Ejecutable local OpenCode `1.18.25`.
- Servidor efímero ligado únicamente a `127.0.0.1`, con Basic Auth y secreto
  aleatorio no persistido.
- Una sola llamada del `OpenCodeSubmissionTransport`: `GET /global/health`.
- Respuesta acotada `200 application/json` con `healthy=true` y
  `version=1.18.25`.
- Cero sesiones, prompts, inferencias, wakes, polling y endpoints adicionales.
- Cierre del proceso y desaparición del listener al terminar.

## Hipótesis adversariales por comprobar

| Hipótesis | Criterio de rechazo |
| --- | --- |
| Health concede autoridad de wake | La evidencia sólo acredita disponibilidad y versión; no reserva, autoriza ni ejecuta una entrega. |
| El transporte puede enviar un POST accidental | El cliente invoca literalmente un único GET y no construye cuerpo E4. |
| El servidor queda expuesto o persistente | Host numérico `127.0.0.1` y cierre comprobado al finalizar. |
| La credencial se filtra a Git, logs o evidencia | Se genera y consume en el proceso; la salida sólo contiene campos saneados de salud. |
| Una versión distinta pasa inadvertida | El resultado sólo procede con versión exacta `1.18.25`. |
| Una respuesta hostil amplía consumo o diagnóstico | El transporte conserva timeout, límite de bytes, JSON estricto y error constante. |

## Evidencia observada

- `opencode --version` informó exactamente `1.18.25`.
- El proceso efímero escuchó en `TCP 127.0.0.1:4096 (LISTEN)`; la comprobación
  fallaba cerrada si no encontraba esa forma exacta.
- `OpenCodeSubmissionTransport` abrió una sola consulta con método `GET`, path
  `/global/health`, timeout de 2 segundos y límite de respuesta de 4096 bytes.
- La respuesta fue `200 application/json`, `healthy=true` y
  `version=1.18.25`.
- La ejecución declaró un request, cero POST, cero sesiones, cero prompts y
  `wake=false`; el código de orquestación no contenía otra llamada cliente.
- El secreto aleatorio sólo transitó por variables del proceso, no apareció en
  stdout ni se añadió al árbol. El log temporal del servidor se eliminó al
  cerrar.
- El cleanup terminó el proceso y una comprobación posterior confirmó
  `listener_absent` en el puerto 4096.

## Resultado de los ataques

| Hipótesis | Resultado | Límite conservado |
| --- | --- | --- |
| Health concede autoridad de wake | Rechazada. Ningún guard, reserva, ledger, coordinador o puerto wake fue invocado. | Health sólo acredita disponibilidad/versionado. |
| El transporte puede enviar un POST accidental | Rechazada para esta ejecución: la única invocación fue GET con body `None`. | La existencia del transporte de submission sigue siendo una capability no activada. |
| El servidor queda expuesto o persistente | Rechazada: listener numérico loopback y ausencia posterior comprobada. | No demuestra aislamiento frente a otro proceso local comprometido. |
| La credencial se filtra a Git, logs o evidencia | No se observó filtración: stdout saneado y secreto ausente del árbol. | Como todo secreto de proceso, pudo existir transitoriamente en memoria/entorno local. |
| Una versión distinta pasa inadvertida | Rechazada: cliente y aserción exigieron `1.18.25` exacto. | Cualquier upgrade exige una revisión nueva. |
| Una respuesta hostil amplía consumo o diagnóstico | Mitigada por el transporte ya probado: timeout, bytes y parser estrictos. | Este preflight nominal no sustituye sus pruebas hostiles unitarias. |

## Veredicto

E4-L demuestra que el transporte concreto puede autenticar y leer salud real en
loopback bajo sus límites. No demuestra capacidad de agente, proveedor,
sesión, inferencia, correlación terminal ni seguridad del flujo completo. El
siguiente incremento debe conservar esas operaciones separadas y requiere
autorización nueva. Commit, push y release continúan fuera de esta tarjeta.

## Checks finales

- Tarjeta `epistates/task-card/v1`: `VALID`.
- Pruebas focales de `opencode_http`: 11, `OK`.
- Suite completa fuera de la restricción de sockets Unix del sandbox: 885,
  `OK (skipped=1)`. La primera ejecución confinada falló antes de la lógica del
  proyecto al intentar crear el socket temporal de una prueba de seguridad; la
  repetición con ese permiso disponible pasó sin cambios de código.
- `git diff --check`: limpio.
- Alcance del árbol: sólo esta tarjeta, este reporte y la actualización del
  plan E4; sin cambios de código ni configuración.
