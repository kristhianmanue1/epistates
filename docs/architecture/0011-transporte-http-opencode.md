# ADR-0011 — Transporte HTTP loopback OpenCode de mínimo privilegio

**Estado:** aceptado para código interno probado sin red real.
**Fecha:** 2026-08-28. **Depende de:** ADR-0007, ADR-0009 y ADR-0010.

## Contexto

E4-H/J sólo usaban callables inyectados. Para poder integrar OpenCode sin
convertir el observador en emisor se necesita una implementación HTTP concreta,
pero una sola capability genérica mezclaría lectura, submission, redirects,
proxies, tamaños no acotados y manejo accidental de secretos.

La [documentación pública del servidor OpenCode](https://opencode.ai/docs/server/)
establece HTTP loopback y Basic Auth mediante `OPENCODE_SERVER_PASSWORD`; el
usuario por defecto es `opencode` y puede configurarse por separado.

## Decisión

Se crean dos transportes internos y no exportados desde la API raíz:

- `OpenCodeReadTransport`: sólo cuatro GET necesarios para health, status,
  user message E4 y listado acotado de mensajes;
- `OpenCodeSubmissionTransport`: sólo GET health/agent y POST
  `/session/<id>/prompt_async` con el cuerpo E4 exacto.

Ambos:

1. conectan únicamente a `127.0.0.1` y puerto explícito;
2. requieren username y password inyectados; nunca leen entorno, archivos o
   keychains;
3. usan `http.client.HTTPConnection` directamente, sin proxy ni redirect;
4. fijan timeout entre 0.1 y 10 segundos, conexión `close`, y
   `Accept-Encoding: identity`;
5. limitan request a 4096 bytes y response configurable entre 1 KiB y 2 MiB;
6. exigen status exacto (`200` GET, `204` POST), JSON UTF-8, content type JSON,
   claves únicas, números finitos, profundidad y nodos acotados;
7. convierten cualquier fallo en `OpenCodeTransportError` sin URL, body,
   respuesta o credencial;
8. comprueban que su `base_url` numérica coincide con la declarada por el
   adapter.

El transporte read-only sólo admite mensajes `msg_e4_<nonce>`. El de submission
valida messageID, agente, proveedor/modelo, prompt fijo y conjunto exacto de
campos antes de abrir conexión.

## Consecuencias

- El observador no puede invocar POST usando su transporte.
- No hay descubrimiento de puerto, DNS, redirects, compresión, SSE ni polling.
- Basic Auth viaja sobre HTTP loopback, como documenta OpenCode. Protege frente
  a clientes locales no autenticados, no frente a un host ya comprometido.
- El password existe transitoriamente en memoria para construir el header, pero
  no aparece en `repr`, errores, evidencia ni persistencia de Epistates.
- La capa limita bytes antes de parsear y después aplica límites estructurales.

## Frontera de autoridad

`OpenCodeSubmissionTransport` es una capability con efecto si se usa
directamente. Su existencia no autoriza invocarla: debe permanecer interna y
ser alcanzada sólo a través de `WakeSubmissionCoordinator`, después de guard,
reserva durable, binding y segunda lectura del kill switch. Este corte no la
conecta a runtime ni abre sockets reales.

Levantar servidor, obtener credenciales, crear sesión, hacer un prompt real,
activar polling/wake, exportar API pública, commit, push o release requiere
otra autorización.
