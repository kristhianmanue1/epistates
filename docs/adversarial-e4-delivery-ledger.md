# Ronda adversarial — ledger durable local E4

Fecha: 2026-08-28

Tarjeta: `e4-delivery-ledger-implementation`

Decisión: **PROCEED para el ledger local; integración, proveedor y wake bloqueados.**

## Ataques y resultado

| Ataque | Resultado |
| --- | --- |
| Dos writers parten del mismo estado | `BEGIN IMMEDIATE` y CAS permiten un solo ganador; el otro recibe `conflict`. |
| Crash después de persistir `submitting` | Un store nuevo recupera `submitting`; sólo una transición explícita puede marcar `ambiguous`. |
| Salto `reserved -> submitted` | Rechazado por el grafo cerrado de transiciones. |
| Reabrir un estado terminal | Rechazado; no existen salidas desde `completed`, `failed` o `ambiguous`. |
| Tratar `submitted` como final | El estado actual permanece `submitted` hasta evidencia terminal explícita. |
| Evidencia ausente o no saneada | `submitted` y estados terminales exigen clase con sintaxis limitada y digest SHA-256. |
| Reloj retrocede | La transición se rechaza sin mutar intento ni historial. |
| Colisión de nonce o recibo | Sólo el replay byte-equivalente de la creación es idempotente; otra carga recibe `duplicate`. |
| Base con versión futura | Se deshabilita antes de crear tablas v1; la base desconocida queda intacta. |
| Ledger usado como transporte | El módulo no importa ni invoca red, OpenCode, prompts, sesiones o `WakeGuardStore`. |
| Publicación accidental de API | Se eliminó la exportación desde `epistates.__init__`; el módulo sigue interno. |

## Hallazgos corregidos

1. La primera implementación no conservaba la versión observada del proveedor;
   se añadió `provider_version` al binding durable.
2. La primera inicialización comprobaba la versión después de crear tablas y
   podía mutar una base futura; el gate de versión ahora ocurre primero.
3. Exportar el store desde la raíz habría ampliado la API pública sin decisión;
   esa exportación se retiró.
4. Estado actual e historial deben cambiar juntos; ambos se escriben dentro de
   una única transacción SQLite.

## Límite de aceptación

El archivo SQLite es evidencia durable local, no una atestación frente a un
proceso local comprometido. No hay migración, retención, reconciliador, retry,
liberación de cuota ni observación terminal. Integrar el ledger con
`WakeGuardStore` u `OpenCodeWakePort` requiere tarjeta, autoridad y revisión
adversarial nuevas.
