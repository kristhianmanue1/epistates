# Ronda adversarial — E4 guard persistente

**Fecha:** 2026-08-28. **Decisión:** `proceed-for-guard-only`.

## Alcance

Se revisó únicamente `WakeGuardStore`: reserva SQLite de policy, kill switch,
nonce y cuota. No contiene puerto, SDK, red, credencial, callback, wake ni
reactivación.

## Ataques y resultado

| Ataque | Resultado |
| --- | --- |
| Policy deshabilitada o store corrupto | `disabled`, sin reserva. |
| Kill switch y restart | `disabled` persiste; no existe método de desactivación. |
| Replay de nonce o recibo | `duplicate` por índices únicos persistentes. |
| Carrera de dos reservas al mismo destino | Una `reserved`; la otra `rate_limited`. |
| Flood global o por destino | Contadores por ventana, global y por destino, bloquean antes de reservar. |
| Reloj regresivo / TTL | `expired`; no se actualiza la reserva. |
| Cambio silencioso de policy | Mismatch de configuración deja el store `disabled`. |

## Límite crítico

El digest recibido se valida estructuralmente, pero este guard no consulta el
store E3 ni llama un puerto. Esa verificación de recibo aceptado y el efecto
externo deben ocurrir juntos en una tarea posterior, con proveedor concreto y
revisión adversarial fresca. Por tanto, `reserved` no es permiso ni wake.

La ronda inicialmente detectó una carrera de lectura antes de insertar. Se
corrigió mediante `BEGIN IMMEDIATE` antes de consultar cuota y se reejecutó la
prueba concurrente en Python 3.12 y 3.9.

## Evidencia y decisión

Pruebas focales cubren reinicio, kill switch, cuotas, replay, TTL, corrupción y
concurrencia. `proceed-for-guard-only`: se acepta el componente inerte; queda
bloqueado todo adaptador, red, credencial y reactivación real.
