# PLAN EPI-E4-001 — diseño de reactivación soportada

**Estado:** diseño autorizado; implementación y activación bloqueadas. **ADR:** [ADR-0007](../architecture/0007-reactivacion-soportada.md).

## Invariantes

- Sólo un `SupportedWakePort` documentado y verificado para un proveedor puede recibir un wake.
- Un recibo E3 aceptado es correlación, nunca autorización.
- Policy, kill switch, rate limit y nonce son persistentes, independientes y fail-closed.
- Un resultado ambiguo reserva nonce/cuota y exige recuperación humana o contrato explícito; no hay retry implícito.
- Wake no amplía privilegios a dispatch, mutación Git, aceptación, publicación ni inspección con efectos.

## Tareas

```text
TAREA EPI-E4-001-A — contrato y threat model documental
  Produce: ADR-0007, threat model y task-card válida.
  [x] Separar señal, policy, cuota/nonce, kill switch, puerto y resultado.
  [x] Declarar interfaz abstracta sin elegir proveedor.
  [x] Fijar condiciones de parada y resultados cerrados.

TAREA EPI-E4-001-B — revisión adversarial de diseño
  Produce: proceed-for-implementation, fix-and-retry o escalate.
  [x] Atacar confused deputy, replay, doble wake, caída, reloj, cuotas,
      kill switch, endpoint falso, resultado ambiguo y ampliación de alcance.

TAREA EPI-E4-001-C — guard persistente sin efecto externo
  Requiere: tarjeta separada; no elige proveedor.
  Produce: policy, kill switch, nonce y cuota persistentes que sólo reservan.
  Tarjeta: [e4-wake-guard](2026-08-28-e4-wake-guard.task-card.json).
  Estado: implementado y aceptado para reserva local inerte tras
    [ronda adversarial](../adversarial-e4-wake-guard.md).

TAREA EPI-E4-001-D — adaptador de proveedor (bloqueada)
  Requiere: autorización explícita nueva, proveedor público elegido, capabilities
  verificables y ronda adversarial fresca del código final.
  Prohibido: red, credenciales, wake real o reactivación hasta entonces.
  Estado: puerto OpenCode simulado y limitado por la
    [task-card](2026-08-28-e4-opencode-port.task-card.json); activación sigue bloqueada.

TAREA EPI-E4-001-E — ciclo durable de entrega asíncrona
  Produce: ADR-0009, threat model actualizado, tarjeta y ronda adversarial.
  [x] Separar reserved, submitting, submitted, completed, failed y ambiguous.
  [x] Fijar transiciones monotónicas, crash windows y reconciliación sin retry.
  [x] Declarar que HTTP 204 sólo acredita submitted.
  Estado: diseño cerrado; implementación, integración y wake bloqueados.
  Tarjeta: [e4-delivery-lifecycle](2026-08-28-e4-delivery-lifecycle.task-card.json).

TAREA EPI-E4-001-F — ledger durable local
  Produce: módulo SQLite interno, pruebas, tarjeta y ronda adversarial.
  [x] Creación idempotente y binding de recibo, destino, proveedor y cuerpo.
  [x] CAS monotónico con historial append-only atómico.
  [x] Restart, crash en `submitting`, concurrencia y esquema desconocido.
  Estado: implementación local cerrada; API pública, integración y wake bloqueados.
  Tarjeta: [e4-delivery-ledger-implementation](2026-08-28-e4-delivery-ledger-implementation.task-card.json).
```

## Definition of Done del diseño

- ADR, threat model y revisión distinguen señal, correlación, autorización y efecto externo.
- La tarjeta se valida y los enlaces locales son correctos.
- Ningún documento presenta E4 como implementado o habilitado.
- La siguiente tarea debe fijar proveedor, persistencia y pruebas de recuperación.
