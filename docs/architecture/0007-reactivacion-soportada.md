# ADR-0007 — Reactivación soportada, no implícita

**Estado:** aceptado para diseño; runtime bloqueado. **Fecha:** 2026-08-28. **Depende de:** ADR-0004 y ADR-0006.

## Decisión

E4 sólo podrá solicitar reactivación mediante un puerto público, documentado y soportado por el sistema destino. No habrá emulación de UI, API privada, scraping, envío a `tmux`, señal de proceso ni fallback automático. Una señal E3 aceptada no es permiso de wake.

La futura interfaz mínima será un puerto inyectado, no un cliente de proveedor:

```text
SupportedWakePort.capabilities() -> WakeCapabilities
SupportedWakePort.request_wake(WakeRequest) -> WakeResult
```

Antes de `request_wake`, el controlador verifica una policy persistente de habilitación, kill switch persistente, límite global y por destino, nonce de wake único, TTL y binding con el recibo de dispatch. `WakeResult` es cerrado: `queued`, `rate_limited`, `disabled`, `unsupported`, `rejected` o `failed`; ninguno equivale a autoridad, ejecución ni aceptación.

## Flujo obligatorio

```text
reconciliación E3 -> recibo aceptado -> inspección read-only independiente
  -> policy vigente -> reserva atómica de cuota/nonce
  -> relectura de kill switch -> puerto público soportado -> resultado cerrado
```

Toda comprobación fallida impide la llamada. La reserva es durable y un timeout ambiguo no libera cuota ni nonce: una repetición exige recuperación auditable, no retry automático.

## Consecuencias

- E4 requiere estados persistentes separados: policy, kill switch y ledger de cuotas/nonces. Ninguno se deriva de tarjeta, señal, variable de proceso o retorno del proveedor.
- El puerto sólo se habilita tras verificar documentación, versión y capabilities de un proveedor concreto en una tarea posterior.
- La implementación falla cerrada si no hay persistencia, si el reloj o binding de destino es inválido, o si el resultado de red es ambiguo.
- La inspección sigue siendo read-only; wake no permite dispatch, corrección, Git, publicación ni aceptación.

## No decisión

Esta ADR no selecciona proveedor, endpoint, autenticación, SDK, formato ni almacenamiento. Tampoco autoriza código, credenciales, tráfico de red, wake real ni reactivación automática.
