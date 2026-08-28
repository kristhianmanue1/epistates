# Decisiones de arquitectura

Las ADR registran decisiones con alternativas y consecuencias que siguen
vigentes. No se reescriben para cambiar una decisión: una ADR posterior la
sustituye o acota con referencia explícita.

- [ADR-0001](0001-audit-state-v1.md): resultado de auditoría y máquina de
  estados v1.
- [ADR-0002](0002-adopcion-limitada-practicas-skevi.md): prácticas de proceso
  inspiradas en Skevi, sin alterar contratos de Epistates.
- [ADR-0003](0003-gate-estructural-de-planes-diferido.md): gate de planes
  diferido hasta contar con una señal local demostrada.
- [ADR-0004](0004-senal-local-y-consumo-atomico.md): descomposición de la señal
  local en recibo persistente, watcher de mínimo privilegio y reactivación
  posterior.
- [ADR-0005](0005-fuente-local-de-senales.md): bandeja local no confiable y
  requisitos de publicación, recuperación y contención.
- [ADR-0006](0006-adaptador-kqueue-local.md): adaptador macOS de una espera;
  sólo solicita reconciliación local y no despierta tareas.
