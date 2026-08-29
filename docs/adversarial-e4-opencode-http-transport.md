# Ronda adversarial — E4-K transporte HTTP OpenCode

**Fecha:** 2026-08-28. **Artefacto:** código interno no publicado.
**Veredicto:** **PROCEED para implementación sin red real.** Wiring runtime,
servidor, sesión, credenciales reales, prompt,
wake, commit, push y release permanecen bloqueados.

## Ataques y resultado

| Ataque | Resultado |
|---|---|
| SSRF, DNS o hostname alterno | El transporte construye la conexión con `127.0.0.1`; sólo recibe puerto validado. |
| Proxy o redirect a otro origen | Usa `HTTPConnection` directo y rechaza cualquier status distinto de 200/204. |
| Observador intenta POST | `OpenCodeReadTransport` sólo admite cuatro GET con body `None`. |
| Lectura arbitraria de mensajes | El ID directo debe ser exactamente `msg_e4_<nonce>`; status/listado sólo cubren endpoints requeridos. |
| Submission a otro endpoint o cuerpo | Ruta, método, campos, messageID, agente, modelo y prompt fijo se validan antes de conectar. |
| CRLF en credencial | Username usa allowlist y password rechaza CR/LF. |
| Filtración por error o repr | El error es constante y el objeto usa repr opaco; pruebas incluyen respuesta y password señuelo. |
| Redirect con body hostil | Status 3xx se rechaza sin seguirlo ni parsear contenido. |
| Zip bomb | Solicita `identity` y rechaza cualquier Content-Encoding diferente. |
| Content-Length falso o body excesivo | Rechaza longitud inválida/mayor y lee como máximo límite + 1. |
| JSON con duplicados, NaN, UTF-8 inválido o profundidad extrema | Parser estricto y validación iterativa lo rechazan. |
| Mapping hostil durante allowlist | Toda validación ocurre dentro del cierre saneado; no escapa excepción ni se conecta. |
| Base URL del adapter no coincide | Constructor rechaza el wiring antes de cualquier request. |
| Conexión o parseo falla | Siempre intenta cerrar la conexión y sólo expone error saneado. |

## Hallazgos corregidos durante la ronda

1. La validación de submission se ejecutaba antes del bloque que sanea
   excepciones; un Mapping hostil podía filtrar su error. Se movió dentro.
2. La primera allowlist read-only aceptaba cualquier ID `msg_*`. Se restringió
   a IDs E4 derivados de nonce.

## Riesgos residuales y stop rules

- El transporte de submission es una capability peligrosa si se invoca fuera
  del coordinador. Sigue interno, sin exportación raíz ni wiring runtime.
- Basic Auth sobre loopback no protege contra procesos privilegiados o un host
  comprometido. No se presenta como sandbox de seguridad.
- El listado de mensajes expone contenido al proceso durante el parseo, aunque
  Epistates sólo devuelve y persiste un resumen saneado.
- No se probó compatibilidad contra un servidor real; hacerlo enviaría tráfico
  local y requiere autoridad independiente incluso para health.
- No existe gestión de secretos, descubrimiento de puerto, lifecycle de servidor,
  polling ni retry en este corte.

## Evidencia de aceptación

- tarjeta E4-K válida;
- pruebas focales E4-H/I/J/K: 55 casos OK;
- suite completa: 885 pruebas OK, con 1 skip esperado del host;
- enlaces locales válidos y `git diff --check` OK;
- transportes ausentes de la API raíz y sin clientes alternos/proxy/redirect;
- 25 rutas sucias, todas dentro de la unión E4-H/I/J/K; cero staged;
- sin socket OpenCode real, servidor, sesión, credencial, prompt, commit ni push.

El veredicto no autoriza efectos externos ni publicación.
