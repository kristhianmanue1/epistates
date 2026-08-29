# Ronda adversarial — candidata 0.1.0-alpha.2

Fecha: 2026-08-28

Tarjeta: `release-alpha2-preparation`

Estado inicial: **PENDIENTE DEL GATE FINAL**.

## Ataques obligatorios

- version skew entre runtime, metadata, nombre del wheel, README y changelog;
- gate alpha.1 reutilizado como si certificara el `HEAD` actual;
- inventario obsoleto de módulos o package-data;
- wheel único presentado como reproducible;
- import accidental desde checkout/PYTHONPATH durante smoke;
- diferencias Python 3.9/3.12 no evidenciadas o Linux presentado como verificado
  pese a que la cuota impidió iniciar los jobs GitHub;
- documentación empaquetada obsoleta o digest inconsistente;
- E4 interno presentado como wake activo;
- tag/release/PyPI inferidos de tests verdes;
- secretos, credenciales o artefactos de build añadidos al repositorio.

## Veredicto

Pendiente de builds, smoke, CI local y revisión del artefacto final. El run
GitHub `33225053925` quedó bloqueado antes de ejecutar steps por límite de uso;
no certifica ni refuta el código. La matriz macOS/Linux queda manual y Linux se
declara no verificado para este corte.
