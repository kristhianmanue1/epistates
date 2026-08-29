# ADR-0012 — Validación ordenada de permisos efectivos OpenCode

**Estado:** aceptado para implementación interna probada sin red.
**Fecha:** 2026-08-28. **Depende de:** ADR-0008 y ADR-0011.

## Contexto

`GET /agent` devuelve el ruleset combinado, no una lista donde cada regla sea
simultáneamente efectiva. En OpenCode 1.18.25 los defaults se concatenan con la
configuración y la evaluación elige la última coincidencia. Además, OpenCode
puede añadir al final un allow específico de `external_directory` para su
directorio interno de resultados truncados.

Rechazar cualquier `allow` histórico produce falsos bloqueos; aceptar el nombre
del agente sin revisar el orden permite configuraciones que reabren herramientas.

## Decisión

`OpenCodeWakePort.capabilities()` valida fail-closed:

1. health y versión exacta;
2. exactamente un agente con nombre configurado;
3. modo `primary` y modelo exacto `{providerID: zai, modelID: <configurado>}`;
4. ruleset tipo lista, acotado y formado sólo por reglas string conocidas;
5. existencia de un deny global `permission=*`, `pattern=*`;
6. después del último deny global, ninguna regla puede reabrir una herramienta;
7. el tail sólo admite `external_directory/* -> deny` y, opcionalmente, un
   único allow específico absoluto, sin traversal ni controles, terminado en
   `/opencode/tool-output/*`.

La excepción de truncado es un segundo gate de filesystem, no una herramienta.
El deny global posterior mantiene ocultas/denegadas las herramientas. Cualquier
regla `allow`/`ask` de herramienta después del deny, wildcard external allow,
duplicado, path distinto o forma desconocida resulta `unsupported`.

## Consecuencias

- Los defaults visibles antes del deny no se confunden con permisos efectivos.
- Un cambio de orden o shape en OpenCode falla cerrado.
- La política queda ligada a OpenCode `1.18.25`; otra versión requiere revisión.
- No se interpreta el prompt, no se consulta provider y no se prueba inferencia.
- La validación no autoriza submission: guard, ledger, kill switch y autoridad
  siguen siendo requisitos independientes.

## Alternativas rechazadas

- **Cero allow/ask en el payload:** contradice el ruleset combinado de OpenCode
  y no representa su semántica de última coincidencia.
- **Confiar sólo en `* -> deny`:** no detecta reaperturas posteriores.
- **Aceptar cualquier excepción external:** ampliaría filesystem sin binding al
  único uso interno observado.

## Frontera

Servidor real, credenciales, cambio de `opencode.json`, sesión, prompt, wake,
wiring runtime, commit, push, tag y release requieren autoridad separada.
