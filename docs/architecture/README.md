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
- [ADR-0007](0007-reactivacion-soportada.md): frontera documental para wake
  público, límites persistentes y kill switch; runtime aún bloqueado.
- [ADR-0008](0008-opencode-wake-port.md): puerto OpenCode loopback con GLM de
  Z.ai configurado en OpenCode; sólo simulado.
- [ADR-0009](0009-entrega-wake-asincrona.md): ciclo durable y monotónico para
  distinguir reserva, envío, finalización, fallo y ambigüedad; sólo diseño.
- [ADR-0010](0010-correlacion-terminal-opencode.md): correlación exacta por
  nonce/messageID y observación terminal fail-closed.
- [ADR-0011](0011-transporte-http-opencode.md): transportes HTTP loopback
  separados para lectura y submission.
- [ADR-0012](0012-permisos-efectivos-opencode.md): validación ordenada del
  ruleset de agente y excepción interna de truncado acotada.
