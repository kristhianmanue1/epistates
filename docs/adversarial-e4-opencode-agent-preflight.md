# Ronda adversarial — preflight de agente OpenCode E4-M

Fecha: 2026-08-28

Tarjeta: `e4-opencode-agent-preflight`

Decisión: **BLOCKED para activación E4; PARTIAL para cierre formal E4-M.**

## Criterios

- Servidor efímero OpenCode `1.18.25`, autenticado y ligado a `127.0.0.1`.
- Exactamente dos consultas: `GET /global/health` y `GET /agent`.
- Exactamente un agente `epistates-inspect`, modo `primary` y modelo
  `zai/glm-5.2`.
- Cero acciones efectivas `allow` o `ask`; cualquier excepción heredada bloquea
  activación aunque `opencode.json` declare deny.
- Cero sesiones, prompts, inferencias, wakes y endpoints adicionales.
- Evidencia limitada a metadatos y conteos saneados; nunca secreto, prompt ni
  payload completo del agente.

## Ataques por resolver

| Hipótesis | Regla adversarial |
| --- | --- |
| Configuración declarada equivale a configuración efectiva | Rechazar: la decisión se toma sólo sobre `/agent`. |
| Un deny general neutraliza excepciones posteriores | Rechazar ante cualquier regla efectiva `allow` o `ask`. |
| Nombre correcto basta para proceder | Rechazar si modo, proveedor o modelo difieren. |
| Agent preflight autoriza wake | Rechazar: presencia/configuración no son autoridad de entrega. |
| La inspección puede filtrar prompts o credenciales | Emitir únicamente campos saneados y conteos. |

## Veredicto

## Evidencia observada

- OpenCode `1.18.25` escuchó efímeramente sólo en
  `127.0.0.1:4096`, con Basic Auth y secreto aleatorio no persistido.
- Se hicieron exactamente dos requests, ambos GET: `/global/health` y
  `/agent`; cero POST, sesiones, prompts y wake.
- Health fue sano y de versión exacta `1.18.25`.
- `/agent` devolvió exactamente un `epistates-inspect`, modo `primary`, modelo
  `zai/glm-5.2`.
- La lista combinada contiene 15 reglas: 5 `deny`, 6 `allow` y 4 `ask`. Un
  primer criterio que rechazaba cualquier regla no-deny resultó incorrecto:
  confundía defaults conservados con la decisión efectiva de última
  coincidencia.
- Un intento correctivo confirmó el orden final: índice 12 `* -> deny`, índice
  13 `external_directory/* -> deny` e índice 14 una excepción específica
  `external_directory -> allow`; no se expuso su path.
- La [construcción exacta del agente en OpenCode 1.18.25](https://github.com/anomalyco/opencode/blob/v1.18.25/packages/opencode/src/agent/agent.ts)
  concatena defaults y reglas del agente y añade una excepción para el glob de
  truncado si no encuentra un deny explícito para ese glob. El
  [evaluador de permisos 1.18.25](https://github.com/anomalyco/opencode/blob/v1.18.25/packages/opencode/src/permission/index.ts)
  usa la última regla coincidente.
- No se emitieron patrones, paths, prompts, payload completo ni secretos.
- El proceso terminó y una comprobación posterior confirmó
  `listener_absent` en el puerto 4096.

## Resultado adversarial

| Hipótesis | Resultado | Consecuencia |
| --- | --- | --- |
| Configuración declarada equivale a efectiva | Rechazada: `/agent` y la semántica de evaluación son necesarios. | El archivo aislado no prueba mínimo privilegio. |
| Un deny general neutraliza excepciones posteriores | Parcial: `* -> deny` posterior anula defaults para herramientas, pero una excepción `external_directory` específica queda después. | No se demostró una herramienta ejecutable, pero falla el criterio literal deny-only. |
| Nombre correcto basta | Rechazada como criterio suficiente; nombre, modo y modelo pasan, permisos no. | No procede wake. |
| Agent preflight autoriza wake | Rechazada: no se invocó guard, ledger, coordinador ni POST. | El diagnóstico no concede autoridad. |
| La inspección filtra prompts o credenciales | No se observó filtración; la salida se limitó a nombres, modelo y conteos. | El secreto sólo existió transitoriamente en el entorno de procesos. |

## Desviación del contrato

El criterio inicial de “rechazar cualquier allow/ask presente” produjo un falso
bloqueo porque no consideraba la evaluación por última coincidencia. Para
corregirlo se ejecutaron dos intentos efímeros adicionales, cada uno con los
mismos dos GET permitidos. En total fueron tres servidores secuenciales y seis
GET, sin POST ni endpoints nuevos. Aunque cada escalación fue acotada y dejó el
listener cerrado, el total excede la lectura literal de “exactamente dos
consultas” de la tarjeta. La evidencia técnica es útil, pero el cierre formal no
puede ser `PROCEED` bajo ese contrato.

## Veredicto

E4-M obtiene un diagnóstico concluyente: el endpoint y agente existen y el deny
global posterior mantiene las herramientas bloqueadas, pero OpenCode añade una
excepción específica posterior de `external_directory`. No se demostró una ruta
ejecutable porque las herramientas siguen denegadas; aun así, la tarjeta exigía
cero `allow`/`ask` y se excedió su presupuesto literal de requests. Su DoD falla
cerrado y no debe conectarse el coordinador ni ejecutarse un wake.

La siguiente tarea debe decidir explícitamente entre: (a) aceptar esa excepción
interna bajo una política basada en permisos efectivos y probar que ninguna
herramienta queda visible, o (b) configurar un deny exacto para el glob de
truncado. Corregir configuración, crear sesión, enviar prompt, commit, push y
release requieren autorización separada.

## Checks finales

- Tarjeta `epistates/task-card/v1`: `VALID`.
- Pruebas focales HTTP/wake: 16, `OK`.
- Suite completa: 885, `OK (skipped=1)`.
- `git diff --check`: limpio.
- Listener 4096 posterior: ausente.
- Árbol: sólo esta tarjeta, este reporte y la actualización del plan E4; sin
  cambios de código ni configuración.
