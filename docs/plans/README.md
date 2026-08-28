# Planes de implementación

Un plan existe sólo cuando una iniciativa coordina varias tareas. Es la fuente
única de pasos y Definition of Done: las tareas que lo ejecutan lo referencian
sin duplicar criterios de aceptación.

- [EPI-SKEVI-001](2026-08-28-adopcion-practicas-skevi.md): adopción limitada de
  prácticas de diseño, desarrollo y documentación.
- [EPI-E3-001](2026-08-28-e3-senal-local.md): diseño de recibos de señal local
  antes de watcher o reactivación; incluye la
  [task-card E3a](2026-08-28-e3a-receipt-contract.task-card.json) y la
  [propuesta de recibo](2026-08-28-e3a-receipt-design.md) con su
  [task-card de diseño](2026-08-28-e3a-receipt-design.task-card.json).
  El adaptador de eventos está limitado por la
  [task-card kqueue E3b](2026-08-28-e3b-kqueue-adapter.task-card.json).
- [EPI-E4-001](2026-08-28-e4-reactivation-design.md): diseño de reactivación
  soportada; runtime bloqueado hasta una autorización y contrato posteriores.

Un plan no concede permisos. Cambios de runtime, contratos, operaciones Git
protegidas o activación de adaptadores requieren la autoridad que corresponda.
