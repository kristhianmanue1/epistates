# Changelog

Todas las versiones notables de Epistates se documentan aquí. El formato se
inspira en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y el
versionado del paquete sigue [PEP 440](https://peps.python.org/pep-0440/).

> **Estado experimental.** Epistates es software experimental sin ninguna
> garantía. Las versiones `-alpha` pueden cambiar sin previo aviso. Una entrada
> en este archivo no prueba publicación por sí sola: cada versión declara su
> estado y la publicación se contrasta con el tag y la release remotos.

## [Unreleased]

No hay cambios posteriores a la candidata `0.1.0-alpha.2`. La candidata sigue
sin tag ni publicación; cualquier release requiere autoridad separada.

## [0.1.0-alpha.2] - Unreleased

Candidata experimental posterior a alpha.1. **No está publicada**: la versión
PEP 440 es `0.1.0a2`, pero el tag humano `v0.1.0-alpha.2` no existe mientras el
mantenedor no autorice el gate final y las operaciones de publicación.

### Added

- E3: recibos de señal locales atómicos, expirables y deduplicables; inbox
  fail-closed y adaptador macOS kqueue que sólo solicita reconciliación.
- E4: guard persistente, kill switch, cuota/nonce, ledger durable, reserva
  atómica, coordinador de submission y reconciliador terminal.
- Puerto, observador y transportes HTTP OpenCode 1.18.25 con Basic Auth,
  loopback numérico, límites de bytes/JSON, correlación messageID y validación
  ordenada de permisos efectivos.
- Manifiesto de proyecto y prácticas ADRC/Skevi adoptadas de forma acotada.
- CI para macOS/Linux sobre Python 3.9 y 3.12.

### Security and governance

- Señal, detección, reconciliación, autorización y efecto externo permanecen
  separados. Un evento o health check nunca concede permiso.
- E4 se distribuye como infraestructura interna **inactiva**: sin daemon,
  polling, sesión automática ni wake habilitado.
- La excepción interna `external_directory` de OpenCode sólo se acepta después
  de un deny global de herramientas y bajo forma acotada de truncado.
- Los resultados ambiguos no se reintentan automáticamente y consumen la
  reserva/cuota correspondiente.

### Known limitations

- El adaptador de eventos kqueue es sólo macOS; Windows no está soportado.
- OpenCode queda ligado a la versión auditada `1.18.25` y `zai/glm-5.2`.
- No existe aún una activación runtime E4 ni un wake real autorizado.
- PyPI permanece sin publicar.

## [0.1.0-alpha.1] - 2026-08-12

Primera prerelease experimental, reproducible y auditable de Epistates,
publicada en GitHub tras autorización separada del mantenedor. El tag
`v0.1.0-alpha.1` apunta al cierre H4 `5d7a34e`; la release distribuye el wheel y
su checksum. PyPI permanece sin publicar.

La versión PEP 440 de la distribución es `0.1.0a1`. El tag humano solicitado es
`v0.1.0-alpha.1`: ambos nombres identifican el mismo corte, pero **no** son
intercambiables como cadenas (PEP 440 normaliza `0.1.0a1`).

### Alcance real de este corte

El paquete distribuye el runtime Python puro de contratos y validación, sin
dependencias de ejecución. El alcance funcional corresponde a los hitos H1–H4
cerrados del plan inicial:

- **H1 — contrato `task-card/v1`**: schema, fixtures y validador local
  read-only. El validador sólo acepta identificadores de un catálogo cerrado;
  no resuelve checks ni inicia procesos.
- **H2 — resultado de auditoría y máquina de estados**: schema y validador
  `audit-result/v1`, máquina de estados pura `apply_audit`, fixtures y pruebas.
- **H3 — adaptador `opencode-tmux/v1`** con cinco sub-cortes cerrados tras
  rondas adversariales independientes:
  - Slice1: contrato neutral `adapter-capabilities/v1`, preflight puro
    fail-closed y resultado portable `preflight-result/v1`.
  - Slice2: observación read-only real del host (`HostRunner` inyectable +
    `observe_opencode_tmux`).
  - Slice3: entrega literal opencode-tmux y recibo `dispatch-receipt/v1`.
  - Slice4: aviso humano `human-notice/v1`, `ReviewRunner` y evidencia
    `review-evidence/v1`.
  - Slice5: puente `review-evidence/v1` → `audit-result/v1` → `apply_audit`
    puro (`audit_review`), con política externa de timestamp, autoridad
    inyectada y anti-downgrade estructural.
- **H4 — contratos instalables para agentes**: descubrimiento estático,
  validación machine-readable, catálogo de schemas y onboarding empaquetado.

### Activos distribuidos vs. activos sólo del repositorio

El wheel `0.1.0a1` contiene 19 módulos Python, metadata `dist-info` con licencia,
los siete schemas canónicos y dos recursos de onboarding bajo
`epistates/data/`. Los recursos se leen mediante `importlib.resources`; los
validadores siguen siendo Python puro y no ejecutan schemas externos. Los
directorios `fixtures/`, `docs/` y `tests/` permanecen fuera del wheel.

### Build reproducible

El wheel se construye de forma determinista fijando los timestamps al del
commit base H4 (`128945f`, timestamp Unix `1786546459`) mediante
`SOURCE_DATE_EPOCH`. Esto produce un wheel reproducible: dos builds
independientes desde los mismos archivos dan idéntico nombre, tamaño,
contenido y SHA-256. El comando determinista está documentado en
[`docs/release-gate.md`](docs/release-gate.md). Un único build **no** es
"reproducible"; la propiedad se atestigua con dos builds comparados.

### Limitaciones experimentales

- **Sin automatización.** No hay gateway, watcher, polling ni señales: la
  inspección es deliberadamente única y manual tras un aviso humano.
- **Sin efectos por defecto.** commit, push, PR, merge, release, creación de
  ramas/worktrees/sesiones y escritura AN-KLA requieren autoridad explícita del
  mantenedor para cada operación.
- **Plataforma.** El adaptador `opencode-tmux/v1` requiere macOS o Linux
  (depende de `tmux`). La validación pura de contratos puede ejecutarse donde
  Python >=3.9 lo haga, pero las plataformas no probadas no se prometen.
- **Stateless.** Los puentes de auditoría y aviso no persisten estado; la
  unicidad global exige persistencia externa.
- **Transporte, no comprensión.** Los recibos atestan transporte/inspección
  técnica, no que el agente leyó, comprendió ni acató la instrucción.

### Metadata del paquete

- Nombre: `epistates`.
- Versión PEP 440: `0.1.0a1` (fuente única: `src/epistates/_version.py`).
- Licencia: Apache-2.0 (`LICENSE`, también embebida en el wheel como
  `dist-info/licenses/LICENSE`).
- Python: `requires-python >=3.9`. Este gate sólo verificó Python 3.9;
  versiones superiores no se probaron aquí y no se afirman en los classifiers.
- Sin dependencias de ejecución.

[Unreleased]: https://github.com/kristhianmanue1/epistates/compare/v0.1.0-alpha.2...HEAD
[0.1.0-alpha.2]: https://github.com/kristhianmanue1/epistates/compare/v0.1.0-alpha.1...HEAD
[0.1.0-alpha.1]: https://github.com/kristhianmanue1/epistates/releases/tag/v0.1.0-alpha.1
