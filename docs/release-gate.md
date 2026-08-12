# Release Gate — Epistates

**Corte:** `0.1.0a1` (PEP 440) · **Tag humano candidato:** `v0.1.0-alpha.1`
· **Fecha de candidata:** 2026-08-11 · **Estado:** gate adversarial local
aceptado; pendiente de commit, integración y autorización del mantenedor.
**No publicada.**

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

- [ ] Comando determinista (fija timestamps al commit base `5f8d58b`,
      timestamp Unix `1786501546`):
      `SOURCE_DATE_EPOCH=1786501546 <venv>/bin/python -m pip wheel --no-deps --no-build-isolation . -w /private/tmp/epistates-release-gate-repro1`
      y de forma análoga con `...-repro2`.
- [ ] Ambos builds producen idéntico **nombre**, **tamaño**, **contenido**
      (bytes a bytes del `.whl`) y **SHA-256**. Un único build **no** atestigua
      reproducibilidad: la propiedad exige dos builds comparados.
- [ ] Sin dependencias declaradas (`dependencies` ausente o vacío).

### 5. Inspección del wheel

- [ ] El wheel contiene el paquete Python `epistates/**/*.py` con **15 módulos**:
      `__init__`, `__main__`, `_version`, `adapter`, `audit`, `audit_review`,
      `contracts`, `dispatch`, `host_observer`, `host_runner`, `human_notice`,
      `preflight`, `review`, `review_runner`, `state`. Estos corresponden 1:1
      con el árbol `src/epistates/` (14 módulos originales + `_version`).
- [ ] `audit_review` y `review` **deben** estar incluidos: son módulos ya
      cerrados y auditados en H3 (Slice5 y Slice4 respectivamente), no módulos
      nuevos. El adversarial mínimo exige que el wheel no introduzca módulos no
      auditados; aquí no introduce ninguno.
- [ ] El wheel incluye la metadata `dist-info`, **incluida la licencia**
      (`epistates-0.1.0a1.dist-info/licenses/LICENSE`).
- [ ] **No** incluye los directorios del repositorio `schemas/`, `fixtures/`,
      `docs/` ni `tests/`: son activos del repositorio, no API distribuida.
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
