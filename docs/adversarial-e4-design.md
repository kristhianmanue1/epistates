# Ronda adversarial — diseño E4

**Fecha:** 2026-08-28. **Decisión:** `proceed-for-implementation-design-only`.

## Pregunta crítica

¿Puede una señal aceptada, retorno del proveedor o tarjeta válida convertirse por sí misma en permiso de reactivar? **No:** el diseño exige policy persistente independiente, kill switch, reserva de cuota/nonce y puerto público verificado; el fallo de cualquiera impide la llamada.

## Hallazgos incorporados

- Rate limit en memoria no sobrevive restart: se exige ledger durable y reserva atómica.
- Revisar kill switch sólo al inicio permite carrera: se exige relectura antes del puerto.
- Retry tras timeout puede duplicar wake: el resultado ambiguo conserva reserva y bloquea retry automático.
- `queued` no demuestra ejecución ni concede pasos siguientes: se trata como dato cerrado.
- Un puerto abstracto podría ocultar API privada: implementación sólo podrá iniciar tras probar interfaz y capabilities públicas del proveedor concreto.

## Límite del dictamen

No hay proveedor, persistencia, código, credencial ni tráfico real para auditar. Este `proceed` acepta sólo diseño documental; no autoriza implementación, wake, reactivación automática ni release.
