# ADR-0009 — Entrega asíncrona durable y reconciliable

**Estado:** aceptado; ledger local implementado, integración y wake bloqueados.
**Fecha:** 2026-08-28. **Depende de:** ADR-0007 y ADR-0008.

## Contexto

El puerto OpenCode devuelve `queued` cuando `prompt_async` responde `204`. Los
preflights reales demostraron que ese acuse puede preceder a reintentos y a un
fallo terminal del proveedor por falta de recursos. También puede existir un
registro `assistant` todavía vacío. Por tanto, ni `204`, ni sesión creada, ni un
mensaje assistant acreditan entrega completa.

## Decisión

E4 separará la reserva de autorización y cuota de la entrega externa mediante
un ledger durable con estados monotónicos:

```text
reserved -> submitting -> submitted -> completed
    |            |             |
    v            v             v
  failed      ambiguous     failed | ambiguous
```

- `reserved`: policy, recibo, destino, nonce, TTL y cuota fueron aceptados;
  todavía no comenzó I/O de proveedor.
- `submitting`: se persistió la intención inmediatamente antes del I/O. Cubre
  el crash entre enviar la petición y registrar su acuse.
- `submitted`: el endpoint público dio un acuse inequívoco, por ejemplo `204`.
  Sólo significa aceptado por la cola local.
- `completed`: una superficie pública soportada mostró finalización terminal
  ligada a la misma entrega. El contenido sigue siendo dato no confiable.
- `failed`: existe un fallo terminal explícito y saneado, con fase y clase; no
  se infiere de silencio, coste cero o ausencia temporal de partes.
- `ambiguous`: timeout, crash, respuesta no parseable o pérdida de binding
  impiden saber si el proveedor aceptó o completó la entrega.

No hay transición hacia atrás. `completed`, `failed` y `ambiguous` son
terminales para el nonce. Ningún estado libera cuota ni autoriza retry. Un nuevo
intento requerirá una decisión independiente, nonce nuevo y enlace al intento
anterior.

## Escritura y reconciliación

Cada transición usa compare-and-swap sobre estado esperado y conserva:

- digest del recibo E3, destino y nonce;
- proveedor, agente, modelo y versión observada;
- digest del cuerpo fijo, nunca credenciales ni respuesta completa;
- timestamps UTC, fase, clase de resultado y evidencia saneada;
- identificador de sesión/solicitud hasheado o referencia opaca mínima.

Al arrancar, la reconciliación es la fuente de verdad. Primero inspecciona sin
efectos `submitting` y `submitted`; sólo aplica una transición cuando una API
pública permite ligar de forma inequívoca el resultado. Si no puede hacerlo,
marca `ambiguous`. Nunca reenvía durante reconciliación.

## Crash windows

- Crash antes de `submitting`: queda `reserved`; no hay prueba de I/O y aun así
  no se envía automáticamente.
- Crash en `submitting`: resultado `ambiguous` salvo que el proveedor ofrezca
  idempotencia o consulta por request id documentada.
- Crash después de `submitted`: reconciliar el resultado; no repetir el prompt.
- Fallo al persistir una transición: conservar el estado anterior y bloquear
  nuevos efectos.

## Consecuencias

- `DeliveryLedgerStore` implementa el ledger interno SQLite y conserva cada
  transición en un historial append-only dentro de la misma transacción que el
  cambio CAS. No se exporta aún desde la API raíz del paquete.
- `WakeDeliveryCoordinator` puede crear la reserva de cuota y el primer evento
  `reserved` en una sola transacción, únicamente cuando guard y ledger apuntan
  al mismo archivo SQLite. Un fallo o colisión revierte ambas escrituras.
- `OpenCodeWakePort.request_wake() == queued` no podrá cerrar una entrega.
- La integración futura requiere una interfaz separada de observación terminal;
  no se ampliará silenciosamente el puerto de envío.
- La falta de saldo, cuota o acceso al modelo se registra como `failed` sólo
  cuando OpenCode la expone terminalmente; sus retries internos no crean nuevos
  permisos Epistates.
- `completed` significa entrega de mensaje, no ejecución correcta de una tarea,
  aceptación humana, autorización posterior ni éxito de proyecto.

## No decisión

Esta ADR no elige schema público, periodo de retención, endpoint de observación,
política de retry ni método de idempotencia de proveedor. La implementación
local y su unión con la reserva no autorizan transición a `submitting`, red,
credenciales, prompt, wake ni automatización.
