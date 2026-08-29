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
- diferencias Python 3.9/3.12 o macOS/Linux no evidenciadas;
- documentación empaquetada obsoleta o digest inconsistente;
- E4 interno presentado como wake activo;
- tag/release/PyPI inferidos de tests verdes;
- secretos, credenciales o artefactos de build añadidos al repositorio.

## Veredicto

Pendiente de builds, smoke, CI y revisión del artefacto final.
