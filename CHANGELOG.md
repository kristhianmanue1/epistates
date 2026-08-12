# Changelog

Todas las versiones notables de Epistates se documentan aquí. El formato se
inspira en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y el
versionado del paquete sigue [PEP 440](https://peps.python.org/pep-0440/).

> **Estado experimental.** Epistates es software experimental sin ninguna
> garantía. Las versiones `-alpha` son candidatas de desarrollo: la API, los
> contratos y el CLI pueden cambiar sin previo aviso. **Ninguna versión se
> considera publicada** hasta que el mantenedor lo autorice explícitamente; la
> presencia de una entrada aquí es sólo la preparación de un candidato local.

## [Unreleased]

Sin cambios desde `0.1.0-alpha.1`. Las líneas futuras requieren autoridad
vigente del mantenedor y, para los hitos, revisión adversarial fresca.

## [0.1.0-alpha.1] - 2026-08-11

Primera candidata experimental local, reproducible y auditable de Epistates.
**No publicada:** el gate adversarial local fue aceptado; tag, push y GitHub
Release quedan pendientes de autorización explícita del mantenedor.

La versión PEP 440 de la distribución es `0.1.0a1`. El tag humano solicitado es
`v0.1.0-alpha.1`: ambos nombres identifican el mismo corte, pero **no** son
intercambiables como cadenas (PEP 440 normaliza `0.1.0a1`).

### Alcance real de este corte

El paquete distribuye **sólo** el runtime Python puro de contratos y
validación, sin dependencias de ejecución. El alcance funcional corresponde a
los hitos H1–H3 cerrados del plan inicial:

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

### Activos distribuidos vs. activos sólo del repositorio

El wheel `0.1.0a1` contiene el paquete Python (`epistates/**/*.py`, 15 módulos
incluyendo `_version`, `audit_review` y `review`, todos ya auditados en H1–H3)
y la metadata `dist-info` (incluida la licencia Apache-2.0 bajo
`dist-info/licenses/LICENSE`). **No** incluye los directorios del repositorio
`schemas/`, `fixtures/`, `docs/` ni `tests/`:

- los validadores son Python puro y no leen `schemas/*.schema.json` en runtime;
  los archivos de schema son documentación JSON Schema descriptiva del
  contrato, no una API cargada desde el paquete instalado;
- los `fixtures/` son activos de desarrollo y pruebas, ligados al repositorio;
- la documentación y las pruebas viven en el repositorio.

`audit_review` y `review` **deben** estar en el wheel: son módulos ya cerrados
y auditados en H3 (Slice5 y Slice4 respectivamente). No son módulos nuevos.

No existe hoy una API `importlib.resources` sobre schemas porque el producto no
los ha designado como API pública distribuida. Promoverlos requeriría una
decisión de diseño y un corte separados; hacerlo en este corte introduciría
rutas inestables. Por honestidad, este alpha declara que **no** lo son.

### Build reproducible

El wheel se construye de forma determinista fijando los timestamps al del
commit base (`5f8d58b`, timestamp Unix `1786501546`) mediante
`SOURCE_DATE_EPOCH`. Esto produce un wheel reproducible: dos builds
independientes desde los mismos archivos dan idéntico nombre, tamaño,
contenido y SHA-256. El comando determinista está documentado en
[`docs/release-gate.md`](docs/release-gate.md). Un único build **no** es
"reproducible"; la propiedad se atestigua con dos builds comparados.

### Limitaciones experimentales

- **Sin automatización.** No hay gateway, watcher, polling ni señales: la
  inspección es deliberadamente única y manual tras un aviso humano.
- **Sin efectos por defecto.** commit, push, PR, merge, release, creación de
  ramas/worktrees/sesiones y escritura AN-KLA están prohibidos o pendientes de
  autoridad explícita del mantenedor.
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

[Unreleased]: https://github.com/kristhianmanue1/epistates/blob/main/CHANGELOG.md
[0.1.0-alpha.1]: https://github.com/kristhianmanue1/epistates/blob/main/CHANGELOG.md
