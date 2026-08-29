# Ronda adversarial — E4-J observador terminal OpenCode

**Fecha:** 2026-08-28. **Artefacto:** implementación local no publicada.
**Veredicto:** **PROCEED sólo para adaptador interno con transporte inyectado.**
Red real, servidor, sesión, credenciales,
polling, wake, commit, push y release permanecen bloqueados.

## Evidencia pública revisada

- La [API pública de servidor](https://opencode.ai/docs/server/) expone health,
  status de sesiones, lectura de mensajes y `prompt_async` con `messageID`.
- La etiqueta [OpenCode v1.18.25](https://github.com/anomalyco/opencode/tree/v1.18.25)
  usa el messageID aportado para el user message y crea el assistant con ese ID
  como `parentID`.
- El binario local observado fue `1.18.25`. No se levantó servidor ni se creó
  una sesión para esta ronda.

## Ataques y resultado

| Ataque | Resultado |
|---|---|
| Dos prompts idénticos sobre una sesión | Cada nonce produce `msg_e4_<nonce>` y digest distinto. |
| Respuesta de otro intento/sesión/modelo/agente | User o assistant no coincide exactamente; `ambiguous`. |
| Dos assistants con el mismo parentID | Se rechaza por duplicidad; `ambiguous`. |
| `204`, `idle` o user existente se presentan como finalización | Ninguno basta; se requiere assistant ligado, terminal y saneado. |
| Assistant vacío | El observador marca ausencia de texto; el reconciliador termina `ambiguous`. |
| Tool part oculto tras texto o estado pending | Tools domina y el reconciliador termina `failed`. |
| `finish=length/tool-calls/otro` | Sólo `stop` puede producir candidato `completed`; el resto es `ambiguous`. |
| Error explícito del assistant | `failed`, sin persistir mensaje ni detalle de error. |
| Timestamp booleano o shape hostil | No se acepta como completion; `ambiguous`. |
| Respuesta excesiva | Más de 100 mensajes/partes o texto mayor a 65536 se rechaza. El transporte futuro aún deberá limitar bytes antes del parseo. |
| Version drift | El constructor sólo admite la versión auditada 1.18.25 y health debe coincidir exactamente. |
| URL con host falso/credenciales | Sólo HTTP loopback sin userinfo, path, query ni fragmento. |
| Convertir observación en envío | El observador sólo invoca GET con body `None`; no contiene cliente de red o proceso. |
| Reintentar tras ambigüedad | No existe loop/polling/retry y el ledger mantiene nonce/cuota. |

## Hallazgos corregidos durante la ronda

1. El diseño inicial carecía de request ID; se añadió correlación determinista
   por nonce al cuerpo y a ambos bindings.
2. La primera implementación aceptaba cualquier versión declarada y cualquier
   finish no vacío. Se fijó 1.18.25 y éxito sólo con `finish=stop`.
3. Se cerraron userinfo en URL, timestamps booleanos y tamaños hostiles.

## Riesgos residuales y stop rules

- El transporte inyectado es una capability externa: un cliente productivo
  necesita límites de bytes/tiempo, autenticación y allowlist propios.
- `GET /session/status` expone un mapa global y el listado trae contenido de la
  sesión. Este corte minimiza y descarta datos después del parseo, pero no limita
  bytes en la capa HTTP porque esa capa todavía no existe.
- Un cambio de versión OpenCode invalida la aceptación hasta repetir análisis
  de schemas, parentID, status y finish.
- `completed` acredita entrega del mensaje fijo; no corrección, autorización,
  aceptación humana ni éxito de proyecto.

## Evidencia de aceptación

- tarjeta E4-J válida;
- pruebas focales E4-H/I/J: 44 casos OK;
- suite completa: 874 pruebas OK, con 1 skip esperado del host;
- enlaces locales válidos y `git diff --check` OK;
- 20 rutas sucias, todas dentro de la unión E4-H/I/J; cero rutas staged;
- sin servidor, sesión, prompt, transporte real, credencial, commit ni push.

El veredicto no autoriza operación externa ni publicación.
