# Release Gate — Epistates

**Corte:** `0.1.0a1` (PEP 440) · **Tag publicado:** `v0.1.0-alpha.1`
· **Fecha de candidata:** 2026-08-11 · **Estado actual:** gate de cierre H4
local `PASS` y revisión adversarial final C1 `PROCEED` (2026-08-12); integrada
en `main` y publicada como GitHub prerelease con wheel/checksum. **PyPI no
publicado.**

Este documento define el gate documental y ejecutable para una candidata de
release de Epistates. Cada criterio es verificable localmente sin red. Tag,
push y GitHub Release **no** son parte de este gate: quedan pendientes de
autoridad explícita del mantenedor.

## Alcance permitido del corte

- Ediciones permitidas: `pyproject.toml`, `README.md`, `CHANGELOG.md`,
  `src/epistates`, `schemas`, `fixtures`, `tests`, `docs`.
- Prohibido en el gate: commit, tag, push, PR, merge, GitHub Release, PyPI,
  red, instalar dependencias externas, crear ramas/worktrees/sesiones,
  gateway/polling/watcher, automatización, `tmux send-keys`/`capture-pane`
  reales, y escritura AN-KLA.
- Artefactos generados (`dist/`, `build/`, `*.egg-info/`, venvs, cachés) **no**
  se rastrean: el `.gitignore` ya cubre `.venv/`, `*.egg-info/` y
  `__pycache__/`; el gate inspecciona el wheel en un directorio **externo** al
  repo.

## Checklist de gate (criterios ejecutables)

### 1. Árbol y diferencias

- [ ] `git status` muestra sólo los archivos editados dentro del alcance
      permitido; sin artefactos generados rastreados.
- [ ] `git diff --check` limpio (sin whitespace errors).
- [ ] Base esperada de la candidata registrada y verificada antes de cualquier
      tag futuro.

### 2. Suite

- [ ] `PYTHONPATH=src <venv>/bin/python -m unittest discover -s tests -p 'test_*.py'`
      termina con exit 0 contra **este** worktree.

### 3. Versión y single-source

- [ ] `src/epistates/_version.py` es la única fuente práctica de la versión.
- [ ] `pyproject.toml` declara `dynamic = ["version"]` y la lee vía
      `[tool.setuptools.dynamic] version = {attr = ...}`; **no** repite un
      `version = "..."` estático.
- [ ] `import epistates; epistates.__version__` devuelve `0.1.0a1` sin red ni
      instalación, leyendo la fuente.

### 4. Construcción reproducible sin red

- [ ] Comando determinista (fija timestamps al commit base H4 `128945f`,
      timestamp Unix `1786546459`):
      `SOURCE_DATE_EPOCH=1786546459 <venv>/bin/python -m pip wheel --no-deps --no-build-isolation . -w /private/tmp/epistates-release-gate-repro1`
      y de forma análoga con `...-repro2`.
- [ ] Ambos builds producen idéntico **nombre**, **tamaño**, **contenido**
      (bytes a bytes del `.whl`) y **SHA-256**. Un único build **no** atestigua
      reproducibilidad: la propiedad exige dos builds comparados.
- [ ] Sin dependencias declaradas (`dependencies` ausente o vacío).

### 5. Inspección del wheel

- [ ] El wheel contiene el paquete Python `epistates/**/*.py` con **19 módulos**:
      `__init__`, `__main__`, `_version`, `adapter`, `audit`, `audit_review`,
      `capabilities`, `contracts`, `discovery`, `dispatch`, `host_observer`,
      `host_runner`, `human_notice`, `onboarding`, `preflight`, `review`,
      `review_runner`, `schemas`, `state`. Corresponden 1:1 con el árbol
      `src/epistates/`. (`discovery` y `capabilities` provienen de H4 Slice1;
      `schemas` y `onboarding` de H4 Slice3. `audit_review` y `review` son
      módulos cerrados en H3, no nuevos.)
- [ ] El wheel incluye **9 package-data**: los **7 schemas canónicos**
      (`epistates/data/schemas/*.schema.json`, fuente única desde H4 Slice3),
      la **guía para agentes** (`epistates/data/onboarding/agent-guide.md`) y la
      **tarjeta mínima** (`epistates/data/onboarding/minimal-task-card.json`).
      Se leen vía `importlib.resources`; los validadores Python no los leen en
      runtime para validar.
- [ ] El repositorio `schemas/` **ya no se distribuye** como directorio externo:
      la fuente canónica está dentro de `epistates/data/schemas/`. El wheel
      **no** incluye `fixtures/`, `docs/` ni `tests/`: son activos del
      repositorio, no API distribuida.
- [ ] El wheel incluye la metadata `dist-info`, **incluida la licencia**
      (`epistates-0.1.0a1.dist-info/licenses/LICENSE`).
- [ ] `METADATA` del wheel muestra `Version: 0.1.0a1`, `License-Expression:
      Apache-2.0`, `Requires-Python: >=3.9`, `Requires-Dist:` ausente, sin
      classifiers de versiones de Python no probadas (sólo `3` y `3.9`) y las
      URLs verificadas.

### 6. Instalación en venv limpio

- [ ] `<venv-build>/bin/python -m venv /private/tmp/epistates-release-gate-smoke`.
- [ ] Instalación **sólo** del wheel local, sin dependencias:
      `/private/tmp/epistates-release-gate-smoke/bin/python -m pip install --no-deps /private/tmp/epistates-release-gate-artifacts/epistates-0.1.0a1-py3-none-any.whl`.

### 7. Smoke desde fuera del repositorio

Ejecutado con `cwd` **fuera** del repo (p. ej. `/private/tmp`), sin
`PYTHONPATH`, sin editable install, sin acceso al checkout principal:

- [ ] `python -c "import epistates; print(epistates.__version__)"` → `0.1.0a1`.
- [ ] `python -c "import importlib.metadata as m; print(m.version('epistates'))"`
      → `0.1.0a1` (comprobación explícita de metadata; debe coincidir con
      `__version__`).
- [ ] `python -m epistates --help` termina con exit 0.
- [ ] El entrypoint `epistates --help` (consola script instalada) termina con
      exit 0.
- [ ] `python -m epistates validate <task-card-minimal.json>` sobre un artefacto
      minimal escrito fuera del repo termina con exit 0 e imprime `VALID`,
      probando la ruta importada desde el wheel (no desde el checkout).
- [ ] Un artefacto inválido (p. ej. schema desconocido) termina con exit distinto
      de 0.
- [ ] `python -m epistates describe --format json` emite un único JSON
      determinista con `stderr` vacío; byte-idéntico entre dos ejecuciones y
      estable ante locale/TZ.
- [ ] `python -m epistates schema list --format json` y
      `schema show <id> --format json` terminan exit `0`; id desconocido exit
      `1`; uso CLI inválido exit `2`.
- [ ] `python -c "from epistates import schemas; ..."` expone `schema_count()==7`,
      `verify_schema_integrity()` sin error y digests recomputados coincidentes.
- [ ] `python -c "from epistates import onboarding; ..."` expone guía, tarjeta
      mínima validada internamente y walkthrough determinista.
- [ ] Autoridad autodeclarada: `validate --format json` y `schema show` nunca
      producen `provenance_verified`/`authorized_to_execute` `true`.

### 8. Reporte

- [ ] Reporte RAG breve con: archivos y comandos a resultado, hash SHA-256 del
      wheel, contenido relevante y riesgos.
- [x] `docs/plan-inicial.md` indica candidata aceptada por el gate local y
      pendiente de las operaciones Git autorizadas; **no** declara release
      publicada.

## Pendiente de autorización (fuera de este gate)

- Tag `v0.1.0-alpha.1`.
- Push de rama/tag.
- GitHub Release / PyPI.
- Auditoría adversarial fresca sobre este corte antes de cualquier publicación.

## Resultado del gate — corrección C1 (2026-08-11, candidata `0.1.0a1`)

> **Sección histórica (evidencia anterior).** Este bloque documenta el gate
> local de la candidata `0.1.0a1` cerrado el **2026-08-11** ANTES de H4 (cuando el
> wheel tenía 15 módulos `.py` y los schemas vivían en el repositorio
> `schemas/`). **No** es el resultado del gate de cierre H4; éste último se
> documenta más abajo en «Resultado del gate de cierre H4». Se conserva como
> evidencia de la línea base de reproducibilidad pre-H4.

Ejecutado por el ejecutor en el worktree
`/private/tmp/epistates-release-alpha1` sobre la base
`5f8d58b3c8bb15fdf8ac4380d8e982f4ab05c32d`. **No publicada.** Esta corrida
corrige los hallazgos C1: build reproducible, conteo de módulos, presencia de
licencia en el wheel y classifiers no probados.

### Comandos a resultado

| Paso | Comando | Resultado |
|---|---|---|
| Suite | `PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` | exit 0, 579 tests OK |
| Diff | `git diff --check` | limpio |
| Build reproducible (×2) | `SOURCE_DATE_EPOCH=1786501546 /Users/krisnova/www/aria/epistates/.venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w /private/tmp/epistates-release-gate-repro{1,2}` | dos wheels idénticos |
| Venv | `/Users/krisnova/www/aria/epistates/.venv/bin/python -m venv /private/tmp/epistates-release-gate-smoke` | creado |
| Install | wheel reproducible instalado con `--no-deps --force-reinstall` y entorno limpio (sin `PYTHONPATH`) en el venv smoke | `Successfully installed epistates-0.1.0a1` |
| Smoke | `python -c` orquestando `python -m epistates --help`, entrypoint `epistates --help`, `validate` nominal e inválido, con `import epistates`, `importlib.metadata.version` y `__version__` en `__all__` | `SMOKE_OK` |

### Reproducibilidad (dos builds comparados)

Comando determinista (fija los timestamps al commit base `5f8d58b`,
timestamp Unix `1786501546`):

```bash
SOURCE_DATE_EPOCH=1786501546 /Users/krisnova/www/aria/epistates/.venv/bin/python \
  -m pip wheel --no-deps --no-build-isolation . -w /private/tmp/epistates-release-gate-repro1
# réplica idéntica con ...-repro2
```

| Build | Nombre | Tamaño | SHA-256 |
|---|---|---|---|
| reconstrucción final 1 | `epistates-0.1.0a1-py3-none-any.whl` | 63400 | `3f5342e138969138ad0c64d09d4996ec3e6b30453964b7d1e5e9d03eee084caa` |
| reconstrucción final 2 | `epistates-0.1.0a1-py3-none-any.whl` | 63400 | `3f5342e138969138ad0c64d09d4996ec3e6b30453964b7d1e5e9d03eee084caa` |

Comparación: `same_name=True`, `same_size=True`, `same_sha256=True`,
`same_bytes=True`. Un único build **no** atestigua reproducibilidad; este gate
reporta dos builds independientes comparados byte a byte.

> Nota: el build no reproducible previo (sin `SOURCE_DATE_EPOCH`) tenía SHA-256
> `59c0874fa6363d605f808cfaf186848d4c0af6cf7d88485ebc782169ff16ebf4` y difería
> sólo en timestamps de seis entradas `dist-info`. El hash reportado a partir
> de esta corrección es el reproducible.

### Contenido exacto del wheel (21 entradas, 15 módulos `.py`)

```
epistates-0.1.0a1.dist-info/METADATA
epistates-0.1.0a1.dist-info/RECORD
epistates-0.1.0a1.dist-info/WHEEL
epistates-0.1.0a1.dist-info/entry_points.txt
epistates-0.1.0a1.dist-info/licenses/LICENSE
epistates-0.1.0a1.dist-info/top_level.txt
epistates/__init__.py
epistates/__main__.py
epistates/_version.py
epistates/adapter.py
epistates/audit.py
epistates/audit_review.py
epistates/contracts.py
epistates/dispatch.py
epistates/host_observer.py
epistates/host_runner.py
epistates/human_notice.py
epistates/preflight.py
epistates/review.py
epistates/review_runner.py
epistates/state.py
```

- El wheel contiene el paquete Python **y** la metadata `dist-info`, **incluida
  la licencia** (`epistates-0.1.0a1.dist-info/licenses/LICENSE`).
- `audit_review` y `review` **deben** estar incluidos: son módulos ya cerrados y
  auditados en H3 (Slice5 y Slice4). No son módulos nuevos; el wheel no
  introduce módulos no auditados.
- **No** incluye los directorios del repositorio `schemas/`, `fixtures/`,
  `docs/` ni `tests/`: son activos del repositorio, no API distribuida.
- **METADATA:** `Version: 0.1.0a1`, `License-Expression: Apache-2.0`,
  `Requires-Python: >=3.9`, sin `Requires-Dist`, classifiers limitados a
  `Python :: 3`, `Python :: 3 :: Only` y `Python :: 3.9` (versiones superiores
  no probadas en este gate), URLs verificadas a
  `github.com/kristhianmanue1/epistates`.

### Versión runtime

Fuente única práctica: `src/epistates/_version.py` (`__version__ = "0.1.0a1"`).
`pyproject.toml` declara `dynamic = ["version"]` y lo lee vía
`[tool.setuptools.dynamic] version = {attr = ...}` (AST, sin ejecutar el
paquete). Runtime expone `epistates.__version__` y lo lista en `__all__`; el
smoke verificó además `importlib.metadata.version("epistates") == "0.1.0a1"` y
`"__version__" in epistates.__all__`.

### Smoke: prueba de la ruta importada

- `import epistates` resuelve a
  `/private/tmp/epistates-release-gate-smoke/lib/python3.9/site-packages/epistates/__init__.py`
  (wheel reproducible instalado), no al checkout.
- `__version__ == 0.1.0a1`; `importlib.metadata.version("epistates") == 0.1.0a1`;
  `"__version__" in epistates.__all__`.
- `python -m epistates --help` → exit 0, imprime `validate`.
- entrypoint `epistates --help` → exit 0, imprime `validate`.
- `python -m epistates validate <task-card-minimal>` (artefacto minimal escrito
  fuera del repo) → exit 0, `VALID`.
- `python -m epistates validate <unknown-schema>` → exit 1, `INVALID`.
- Artefacto minimal declarado fuera del repo porque los `fixtures/` **no** se
  distribuyen: estrategia explícita documentada.

### Riesgos y notas

- **Contaminación por entorno.** La sesión shell exporta `PYTHONPATH=src`
  (heredada del venv editable del checkout principal). Python la absorbe en
  `sys.path` al arranque, lo que haría que un smoke ingenuo importara el
  checkout del worktree en lugar del wheel. El gate la neutraliza: limpia
  `sys.path` para el import directo y lanza los subprocesos (`-m epistates`,
  entrypoint, build, install) con un entorno sin `PYTHONPATH`. La instalación
  del wheel exigió `--force-reinstall` con entorno limpio porque, de lo
  contrario, pip detectaba el `egg-info` regenerado por la build en el worktree
  como “ya instalado”. En un entorno CI/limpio (sin `PYTHONPATH=src`) el smoke
  directo funciona sin neutralización.
- **Builds vía subprocess.** El gate lanza los builds deterministas desde un
  `python -c` del venv smoke (comando permitido), invocando el intérprete del
  venv de build con `SOURCE_DATE_EPOCH` en el entorno. La build directa con
  prefijo `SOURCE_DATE_EPOCH=...` no está en el allowlist de comandos shell;
  el resultado es idéntico al comando determinista documentado arriba.
- **`build/` y `*.egg-info` son subproductos de la build.** Se eliminan del
  worktree tras la construcción; `*.egg-info/` está cubierto por `.gitignore`.
  `build/` no aparece en `.gitignore`; editar `.gitignore` quedó fuera del
  alcance permitido, por lo que se elimina manualmente. Recomendación: añadir
  `build/` y `dist/` al `.gitignore` en un corte autorizado.
- **Plataforma / Python.** Smoke y builds en macOS con Python 3.9
  (CommandLineTools). Linux no probado en este corte; Windows declarado no
  soportado. Versiones de Python superiores a 3.9 no se probaron aquí y no se
  afirman en los classifiers.
- **Sin tag/push/release.** Tag `v0.1.0-alpha.1`, push y GitHub Release quedan
  pendientes de autorización del mantenedor y de auditoría adversarial fresca.

## Resultado del gate de cierre H4

**Fecha:** 2026-08-12. **HEAD:** `128945fae0db9c9134cc55bef0411510f954484c`
(rama `codex/h4-installable-contracts`). **SOURCE_DATE_EPOCH:** `1786546459`
(obtenido con `git show -s --format=%ct HEAD`). **Estado RAG: gate H4 local
PASS.** En el momento de ejecutar este gate, la candidata aún no estaba
publicada; el estado post-publicación se registra en la cabecera y decisión.

Ejecutado por el ejecutor en el worktree
`/private/tmp/epistates-h4-installable-contracts`. Builds y venv en copias
independientes bajo `/private/tmp` (`epistates-h4-src-A/B`, `epistates-h4-wheel-A/B`,
`epistates-h4-venv`, `epistates-h4-smoke-empty`) para no crear `build/` ni
`*.egg-info` en el worktree. Sin red, sin dependencias (`--no-deps
--no-build-isolation`).

### Comandos a resultado

| Paso | Comando | Resultado |
|---|---|---|
| Estado | `git status` / `git diff --check` / `git diff --cached` | nada staged; `diff --check` exit 0; `diff --cached` vacío |
| Suite | `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` | exit 0, **793 OK (1 skipped)** — skip pre-existente tmux |
| Versión | `python -c "import epistates; epistates.__version__"` / `importlib.metadata.version` | `0.1.0a1` (single-source `_version.py`, `dynamic=[version]` vía `attr`) |
| Build reproducible (×2) | `SOURCE_DATE_EPOCH=1786546459 python3 -m pip wheel --no-deps --no-build-isolation <src-A/B> -w <wheel-A/B>` | dos wheels byte-idénticos |
| Venv + install | `python3 -m venv …/epistates-h4-venv` → `env -u PYTHONPATH …/python -m pip install --no-deps --force-reinstall <whl>` | `Successfully installed epistates-0.1.0a1` |
| Smoke | `env -u PYTHONPATH …/python smoke.py` desde cwd vacío fuera del repo | `ALL_SMOKE_OK` |

### Reproducibilidad (dos builds comparados)

| Build | Nombre | Tamaño | SHA-256 |
|---|---|---|---|
| copia A | `epistates-0.1.0a1-py3-none-any.whl` | 108527 | `921c36ea5d399caa163a7394a1ae6281c28022739b07a8ce34bf929c783aecfe` |
| copia B | `epistates-0.1.0a1-py3-none-any.whl` | 108527 | `921c36ea5d399caa163a7394a1ae6281c28022739b07a8ce34bf929c783aecfe` |

Comparación: `same_name=True`, `same_size=True`, `same_sha256=True`,
`cmp` byte-idéntico (exit 0).

> **Recertificación C1 del gate (2026-08-12).** La primera ronda adversarial
> del gate encontró que el README distribuido aún mostraba el
> `SOURCE_DATE_EPOCH=1786501546` pre-H4. Se corrigieron el README y la plantilla
> vigente de este documento a `1786546459`, se reconstruyeron dos copias fuente
> nuevas e independientes y se obtuvo el hash reproducible de la tabla. El hash
> anterior `8a88466f…d00ab11` (108525 bytes) queda superado; la diferencia
> corresponde a la corrección documental incorporada en `METADATA`, no a código
> runtime.

### Inventario del wheel (34 entradas)

- **19 módulos `.py`**: `__init__`, `__main__`, `_version`, `adapter`, `audit`,
  `audit_review`, `capabilities`, `contracts`, `discovery`, `dispatch`,
  `host_observer`, `host_runner`, `human_notice`, `onboarding`, `preflight`,
  `review`, `review_runner`, `schemas`, `state`.
- **9 package-data**: 7 schemas (`epistates/data/schemas/*.schema.json`, fuente
  canónica), guía (`epistates/data/onboarding/agent-guide.md`) y tarjeta mínima
  (`epistates/data/onboarding/minimal-task-card.json`).
- `dist-info` con licencia (`licenses/LICENSE`), `entry_points.txt`
  (`epistates = epistates.__main__:main`), `top_level.txt` = `epistates`.
- `METADATA`: `Version: 0.1.0a1`, `License-Expression: Apache-2.0`,
  `Requires-Python: >=3.9`, **sin `Requires-Dist`**.
- **Sin** `fixtures/`, `docs/`, `tests/` ni `schemas/` externos en el wheel.

### Ruta importada (probada desde cwd vacío fuera del repo)

`env -u PYTHONPATH …/python -c "import epistates"` resuelve a:

```
/private/tmp/epistates-h4-venv/lib/python3.9/site-packages/epistates/__init__.py
```

(venv smoke, no checkout). `importlib.metadata.version('epistates') == '0.1.0a1'
== epistates.__version__`.

### Smoke instalado (ALL_SMOKE_OK)

- `--version` → `0.1.0a1` exit 0; `python -m epistates --help` y entrypoint
  `epistates --help` exit 0.
- `describe --format json`: un único JSON determinista, `stderr` vacío,
  byte-idéntico entre dos ejecuciones.
- `schema list --format json` exit 0 (catálogo de 7); `schema show <id>` exit 0;
  id desconocido exit 1; uso inválido exit 2.
- `schemas.schema_count() == 7`, `verify_schema_integrity()` OK; digests
  recomputados coinciden con los congelados.
- `onboarding.read_agent_guide()` (sin «Viger»), tarjeta mínima validada
  internamente y devuelta como copia fresca, digests verificados, walkthrough
  determinista (alcanza `DONE`).
- `validate` nominal (exit 0 / `VALID`) e inválido (exit 1 / `INVALID`) sobre
  artefactos temporales escritos fuera del repo; `--format json` con reporte
  `epistates/validation-report/v1`.
- Estabilidad ante `LC_ALL`/`TZ`/`PYTHONIOENCODING` (`C/UTC`,
  `ja_JP.UTF-8/Asia/Tokyo`, `ascii/C/America/Buenos_Aires`): `describe` y
  `schema list` byte-estables.
- Autoridad autodeclarada: `validate --format json` (tarjeta con bloque
  `authority`) y `schema show` nunca producen `provenance_verified` ni
  `authorized_to_execute` `true` (`external_unverified` / `false`).

### Ausencia de probing (superficies estáticas)

Las superficies estáticas (`--version`, `--help`, `describe`, `schema list/show`,
`validate --format json`, acceso a recursos y walkthrough) no realizan probing:
cubierto por `tests/test_discovery.py::NoProbingAndStreamSafetyTests`,
`tests/test_machine_validation.py::NoProbingTests`, `tests/test_schemas.py::NoProbingTests`
y `tests/test_onboarding.py::WalkthroughTests` (18 tests, parchean
`subprocess`/`socket`/`urllib`/`get_terminal_size`/reloj y usan proceso real).
No se afirma sandbox.

### Riesgos y notas

- **`build_discovery_document()`** lee ahora dos recursos de onboarding vía
  `importlib.resources` para verificar digests en cada llamada; sigue siendo
  puro y determinista (sin subprocess/socket/reloj/red).
- **Schemas `structural_only`**: la conformidad semántica con un validador JSON
  Schema externo (p. ej. `jsonschema`) no se prueba; queda fuera de alcance.
- **Plataforma / Python**: smoke y builds en macOS con Python 3.9
  (CommandLineTools). Linux no probado; Windows declarado no soportado. Versiones
  de Python > 3.9 no se afirmaron en los classifiers.
- **Sin tag/push/release**: la revisión adversarial final C1 del gate terminó
  `PROCEED`; tag `v0.1.0-alpha.1`, push y GitHub Release siguen pendientes de
  autoridad separada del mantenedor.

### Decisión

**Gate H4 local PASS y adversarial final C1 `PROCEED`.** Reproducibilidad,
inventario, instalación aislada, smoke y no-probing verificados; cero hallazgos
P0/P1/P2. Evidencia adversarial en
[`adversarial-h4-gate.md`](adversarial-h4-gate.md). La GitHub prerelease
[`v0.1.0-alpha.1`](https://github.com/kristhianmanue1/epistates/releases/tag/v0.1.0-alpha.1)
está publicada con el wheel certificado y su checksum. PyPI permanece sin
publicar por ausencia de credenciales configuradas en el host de publicación.
