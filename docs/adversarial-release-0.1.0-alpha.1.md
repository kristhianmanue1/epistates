# Ronda adversarial — candidata 0.1.0-alpha.1

**Fecha:** 2026-08-11. **Decisión:** `proceed` para preparar la candidata.
**Publicación:** no autorizada ni ejecutada.

## Alcance revisado

Se auditó la metadata `0.1.0a1`, la fuente única de versión, README, changelog,
gate documental, contenido del wheel, reproducibilidad byte a byte, instalación
en un venv limpio y CLI desde fuera del repositorio. Esta ronda no autoriza
commit, integración, tag, push, GitHub Release ni PyPI.

## Hallazgos y corrección

La primera ronda reprodujo que dos wheels con contenido descomprimido idéntico
tenían SHA-256 distintos por timestamps de seis entradas `dist-info`. También
encontró texto obsoleto sobre H3, conteo incorrecto de módulos, una afirmación
incorrecta sobre la licencia incluida y classifiers de Python no probados.

La corrección fijó `SOURCE_DATE_EPOCH=1786501546`, limitó los classifiers a la
evidencia disponible, corrigió la superficie distribuida y exportó
`__version__` explícitamente.

## Evidencia independiente

- Suite: 579 pruebas correctas, una omitida.
- `git diff --check`: limpio.
- Dos reconstrucciones finales del controlador desde copias independientes
  produjeron exactamente 63 400 bytes y SHA-256
  `3f5342e138969138ad0c64d09d4996ec3e6b30453964b7d1e5e9d03eee084caa`.
- Los dos wheels finales son iguales byte por byte (`cmp`: exit 0). Las dos
  reconstrucciones previas a la edición final del README también coincidieron
  entre sí, demostrando que el mecanismo determinista no depende de una copia.
- Wheel: 21 entradas, 15 módulos Python; incluye `review`, `audit_review` y
  `dist-info/licenses/LICENSE`; excluye `schemas/`, `fixtures/`, `docs/` y
  `tests/`.
- Metadata: versión `0.1.0a1`, licencia `Apache-2.0`, Python `>=3.9`, sin
  `Requires-Dist`.
- Instalación de un wheel reconstruido en otro venv: correcta y sin
  dependencias.
- Smoke desde `/private/tmp`, sin `PYTHONPATH`: importó desde `site-packages`;
  `epistates.__version__` y `importlib.metadata.version` devolvieron `0.1.0a1`;
  `__version__` está en `__all__`; módulo y entrypoint mostraron ayuda.
- Validación nominal instalada: exit 0 y `VALID`; schema desconocido: exit 1 e
  `INVALID`.

## Riesgos residuales aceptados

- Sólo Python 3.9/macOS fue ejecutado en este gate. `requires-python >=3.9` no
  equivale a una matriz verificada de versiones o plataformas.
- Los schemas JSON, fixtures y docs son activos del repositorio, no API del
  wheel; el runtime usa validadores Python.
- El build reproducible depende de fijar el `SOURCE_DATE_EPOCH` documentado.
- El software continúa siendo experimental y stateless en las fronteras ya
  documentadas por H3.

## Decisión

`proceed` para la candidata local `0.1.0a1` / tag humano futuro
`v0.1.0-alpha.1`. El artefacto cumple el gate reproducible e instalable. Antes
de publicar faltan commit, integración y una autorización explícita separada
para tag, push y GitHub Release.
