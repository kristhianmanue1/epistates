# ADR-0010 — Correlación terminal OpenCode por messageID

**Estado:** aceptado para adaptadores internos con transporte simulado.
**Fecha:** 2026-08-28. **Depende de:** ADR-0009.

## Contexto

El `204` de `prompt_async` no identifica por sí mismo la entrega ni acredita
una respuesta. El cuerpo previo de E4 era idéntico para todos los intentos. Dos
wakes sobre la misma sesión podían compartir destino, agente, modelo y digest,
por lo que leer mensajes después no permitía atribuir una respuesta a un nonce
con certeza.

La [API pública de servidor de OpenCode](https://opencode.ai/docs/server/)
documenta lectura de status y mensajes, además del `messageID` opcional en el
prompt. El código de la etiqueta
[v1.18.25](https://github.com/anomalyco/opencode/tree/v1.18.25) conserva el ID
aportado en el mensaje user y liga el assistant mediante `parentID`.

## Decisión

Para cada nonce E4 válido:

```text
messageID = "msg_e4_" + nonce
body_digest = sha256(canonical_json(body including messageID))
assistant.parentID == messageID
```

`delivery_binding(nonce)`, `request_wake(session_id, nonce)` y
`observe(session_id, nonce)` reciben la misma correlación. El ledger ya conserva
el nonce y el digest; no se cambia su schema SQLite.

El observador OpenCode de este corte:

1. acepta exclusivamente la versión auditada `1.18.25` y una URL HTTP loopback
   sin userinfo;
2. verifica health/version exactos;
3. consulta `GET /session/status`, el user message por ID y como máximo 100
   mensajes recientes;
4. exige user/session/agent/provider/model/prompt exactos y exactamente un
   assistant cuyo `parentID` sea el messageID;
5. sólo clasifica `completed` con timestamp entero, `finish=stop`, texto no
   vacío y sin tools; error explícito produce `failed`; ausencia activa produce
   `pending`; cualquier contradicción produce `ambiguous`;
6. devuelve únicamente booleanos, clase cerrada y digest de evidencia. Nunca
   persiste texto, error, prompt recibido ni respuesta completa.

El transport es inyectado. No existe aún cliente HTTP productivo, polling,
SSE, arranque de servidor ni integración runtime.

## Consecuencias

- Dos prompts byte-equivalentes quedan separados por messageID y digest.
- Un nonce nunca se reenvía durante reconciliación; la correlación no concede
  permiso ni libera cuota.
- `idle` sin user/assistant ligado no significa éxito: termina `ambiguous`.
- Un finish distinto de `stop`, respuesta vacía, duplicada, cruzada, enorme o
  malformada no puede convertirse en `completed`.
- El nonce pasa al proveedor dentro del messageID. Es correlación aleatoria, no
  secreto ni autoridad.

## Riesgos residuales y nueva autoridad

Un transporte productivo deberá limitar bytes y tiempo antes de parsear JSON,
autenticar el loopback si aplica y demostrar que sólo permite los cuatro GET
de observación y el POST ya gobernado. Actualizar OpenCode exige revisar de
nuevo schemas y semántica. Cualquier servidor/sesión real, credencial, polling,
SSE, wake, retry, exportación pública, commit, push o release requiere otra
decisión.
