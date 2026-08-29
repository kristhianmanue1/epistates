# Release Gate — Epistates 0.1.0-alpha.2

**Versión PEP 440:** `0.1.0a2` · **Tag futuro:** `v0.1.0-alpha.2`
**Estado:** gate `PROCEED`; prerelease GitHub **PUBLICADA**. PyPI fuera de alcance.

Este gate certifica exclusivamente el corte alpha.2. El cierre histórico de
alpha.1 permanece en [`release-gate.md`](release-gate.md). El mantenedor
autorizó tag y GitHub Release; decidió explícitamente no publicar en PyPI.

## Alcance funcional del corte

- H1–H4: contratos, validación, auditoría, discovery, schemas y onboarding.
- E3: recibos locales atómicos, inbox/reconciliación y adaptador macOS kqueue
  que sólo señala “hay trabajo”.
- E4: guard, kill switch, cuota/nonce, ledger, reserva atómica, coordinador,
  observación/reconciliación terminal y transportes OpenCode 1.18.25.
- E4 permanece **interno e inactivo**: no existe daemon, wiring runtime, polling
  automático, sesión automática ni wake habilitado.

## Gate ejecutable

1. Árbol y diff acotados; tarjeta válida; enlaces y secretos revisados.
2. Suite completa en Python 3.9 y 3.12.
3. CI local en macOS arm64 y Linux arm64 con Python 3.9/3.12. La matriz GitHub
   se conserva para ejecución manual cuando vuelva la cuota.
4. Versión single-source `0.1.0a2` coherente con metadata y wheel.
5. Dos copias fuente independientes construidas con el mismo
   `SOURCE_DATE_EPOCH`; wheel byte-idéntico por nombre, tamaño y SHA-256.
6. Inventario exacto de módulos, schemas, onboarding y metadata.
7. Instalación del wheel sin dependencias en venvs limpios Python 3.9/3.12.
8. Smoke desde cwd vacío, sin `PYTHONPATH`: import/version, CLI, discovery,
   schemas, onboarding y validación nominal/inválida.
9. Ausencia de repo/docs/tests/fixtures y secretos dentro del wheel.
10. Ronda adversarial fresca del artefacto final.

## Evidencia de la candidata

- **SHA fuente/tag:** `08c925f483fd7db82337f54e42d1ce7f1b35e6c8`.
- **SOURCE_DATE_EPOCH:** `1787966846`.
- **Artefacto:** `epistates-0.1.0a2-py3-none-any.whl`.
- **Tamaño:** `130899` bytes.
- **SHA-256:**
  `6a73a7f53dc691722d6221acb40769a2d916cfd40ed7352460b80110bba4014a`.
- **Reproducibilidad:** dos exportaciones independientes de ese SHA,
  construidas con Python 3.9.6, `--no-deps --no-build-isolation` y el mismo
  epoch, produjeron nombre, tamaño y bytes idénticos (`cmp` exit `0`).
- **Metadata:** `Name: epistates`, `Version: 0.1.0a2`,
  `Requires-Python: >=3.9`.
- **Inventario wheel:** 44 entradas; 29 módulos Python, 7 schemas, 2 archivos
  de onboarding y 6 entradas `dist-info`; cero rutas `test`, `tests`, `docs`,
  `fixtures` o `.git`.
- **Recursos instalados:** 7 schemas, 3 entradas de onboarding y 45 símbolos
  públicos declarados; digest de `agent-guide.md`
  `sha256:c4f3bd46692c4efd39a6221709ec58af9f9d5ad37899861450354577f8ccbe9c`.
- **Secret scan:** sin coincidencias de claves privadas, tokens GitHub/AWS,
  claves OpenAI ni asignaciones obvias de API key dentro del wheel.

## CI local y smoke

- macOS, Python 3.9.6: `891` tests, `OK`, `1 skipped`.
- macOS, Python 3.12.12 Homebrew: `891` tests, `OK`, `1 skipped`.
- Linux arm64, imagen `python:3.9-slim` digest
  `sha256:2d97f6910b16bd338d3060f261f53f144965f755599aab1acda1e13cf1731b1b`:
  `891` tests, `OK`, `1 skipped`.
- Linux arm64, imagen `python:3.12-slim` digest
  `sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a`:
  `891` tests, `OK`, `1 skipped`.
- Los contenedores se ejecutaron sin red; el checkout se montó read-only y se
  probó una copia efímera escribible en `tmpfs`.
- La primera pasada Linux reveló que el mock macOS intentaba parchear símbolos
  `select.kqueue` inexistentes en Linux. Se corrigió sólo el harness con
  `create=True` y constantes falsas; `src/` no cambió. El montaje read-only
  también mostró cuatro tests que crean fixtures temporales, resuelto mediante
  la copia efímera, sin mutar el checkout.
- Wheel instalado con `pip --no-deps` en dos venvs nuevos.
- Smoke del artefacto final en macOS 3.9.6/3.12.12 y Linux arm64
  3.9.25/3.12.14 desde entornos limpios, fuera del checkout y sin
  `PYTHONPATH`: import, versión runtime/metadata, `--help`, `--version`,
  `describe`, `schema list`, `schema show`, validación nominal empaquetada y
  validación inválida con JSON único/exit `1`, todo conforme.
- Tarjeta válida, YAML parseable, enlaces locales válidos y `git diff --check`
  limpio.

## Limitación externa registrada

El run GitHub Actions
[`33225053925`](https://github.com/kristhianmanue1/epistates/actions/runs/33225053925)
no inició ningún step: GitHub lo bloqueó por límite de uso/facturación. Por
decisión explícita del mantenedor, ese bloqueo es una limitación externa, no un
fallo del código. Para este corte, la evidencia autoritativa es la matriz local
macOS arm64 + Linux arm64 con Python 3.9 y 3.12. El workflow no aporta evidencia.

## Inactividad de E4

- El único entry point instalado sigue siendo `epistates.__main__:main`.
- La CLI sólo expone `validate`, `describe` y `schema`; no expone wake, daemon,
  polling ni sesión.
- Los módulos internos E4 no se importan ni exportan desde `epistates.__init__`.
- No se ejecutó OpenCode, tmux, wake, red de proveedor ni reactivación durante
  el gate. E4 permanece interno e inactivo.

## Resultado

El gate técnico local multiplataforma de la candidata está **PROCEED**. La ronda adversarial
final está en [`adversarial-release-0.1.0-alpha.2.md`](adversarial-release-0.1.0-alpha.2.md).
El mantenedor autorizó tag y GitHub Release y excluyó PyPI. La prerelease
[`v0.1.0-alpha.2`](https://github.com/kristhianmanue1/epistates/releases/tag/v0.1.0-alpha.2)
se publicó el `2026-08-29T01:30:12Z`. El tag anotado se resuelve al SHA fuente
exacto; la release no es draft y sí está marcada prerelease. GitHub reporta para
el wheel remoto tamaño `130899` y digest
`sha256:6a73a7f53dc691722d6221acb40769a2d916cfd40ed7352460b80110bba4014a`,
idénticos al artefacto local validado. También se adjuntó el archivo `.sha256`.
No se consultó ni modificó PyPI durante la publicación.

## Verificación posrelease de consumidor

Los activos se descargaron nuevamente mediante `gh release download` a un
directorio temporal sin usar el wheel de build. El `.sha256` remoto validó el
wheel descargado (`OK`), cuyo tamaño fue `130899` bytes. Se instaló con
`pip --no-deps` en un venv nuevo Python 3.12.12 fuera del checkout y sin
`PYTHONPATH`; import/version, `--help`, `--version`, `describe`, `schema list`,
`schema show` y validación del artefacto mínimo empaquetado pasaron. Esto cierra
la ruta release remota → descarga → checksum → instalación → consumo.

La revisión adversarial de este cierre confirmó que sólo cambiaron documentos,
que ninguna afirmación histórica se reescribió como autorización vigente y que
E4-O aparece únicamente como propuesta no autorizada. No se modificaron el tag,
la release, sus activos, runtime, tests ni configuración de activación.
