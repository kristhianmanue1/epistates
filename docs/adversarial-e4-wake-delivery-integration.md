# Ronda adversarial — integración atómica guard + ledger E4

Fecha: 2026-08-28

Tarjeta: `e4-wake-delivery-integration`

Decisión: **PROCEED para reserva local atómica; envío y wake bloqueados.**

## Ataques y resultado

| Ataque | Resultado |
| --- | --- |
| Guard y ledger usan bases distintas | El coordinador queda `disabled` antes de reservar. |
| Falla el insert de delivery después de reservar cuota | Una excepción SQLite revierte reserva y `last_observed_at`; ambos stores quedan fail-closed. |
| Ya existe delivery equivalente pero no reserva | Se trata como `duplicate`; el modo idempotente del ledger independiente no permite coser historiales. |
| Rate limit o kill switch bloquean guard | No se crea intento ni evento de delivery. |
| Payload delivery inválido | Se valida antes de abrir la transacción; no consume cuota. |
| Dos callers compiten por el último cupo | `BEGIN IMMEDIATE` serializa; sólo el ganador crea ambas filas y el evento. |
| Restart después del commit | Reserva e intento reaparecen juntos; delivery continúa en `reserved`. |
| Integración avanza a `submitting` | Imposible: el coordinador sólo llama la creación inicial del ledger. |
| Helper privado se convierte en callback ejecutable | No existe callback ni argv; las primitivas reciben campos tipados y una conexión interna. |
| API pública crece accidentalmente | El coordinador no se exporta desde `epistates.__init__`. |
| Caller omite el coordinador | Los stores conservan compatibilidad y pueden crear estado aislado; la futura integración runtime deberá hacer obligatorio el coordinador. |

## Hallazgos y decisiones

1. Llamar secuencialmente a `guard.reserve()` y `ledger.create_reserved()` no
   era atómico. Se extrajeron primitivas privadas que aceptan la misma conexión.
2. El replay idempotente del ledger aislado sería inseguro en la integración si
   faltara la reserva correspondiente. El coordinador desactiva ese replay y
   revierte ante cualquier fila delivery preexistente.
3. El cambio conserva los métodos públicos existentes y sus pruebas; no fusiona
   las responsabilidades semánticas de cuota y entrega.
4. El archivo compartido reduce la ventana de crash, pero no convierte SQLite
   en atestación frente a un proceso local comprometido.
5. Esta unidad entrega una primitiva atómica, no su adopción por un runtime: no
   se afirma el invariante global mientras los stores puedan llamarse por separado.

## Límite de aceptación

No existe llamada de proveedor, sesión, prompt, transición a `submitting`,
reconciliación, retry ni liberación de cuota. El siguiente efecto externo exige
una tarjeta y autorización separadas, además de una revisión adversarial fresca.
