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

TAREA EPI-E4-001-C — contrato de implementación (bloqueada)
  Requiere: autorización explícita nueva, proveedor público elegido, capabilities
  verificables, diseño de persistencia y ronda adversarial fresca.
  Prohibido: código, dependencias, credenciales, red, wake real o reactivación.
```

## Definition of Done del diseño

- ADR, threat model y revisión distinguen señal, correlación, autorización y efecto externo.
- La tarjeta se valida y los enlaces locales son correctos.
- Ningún documento presenta E4 como implementado o habilitado.
- La siguiente tarea debe fijar proveedor, persistencia y pruebas de recuperación.
