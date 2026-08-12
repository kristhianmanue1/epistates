# Ronda adversarial — H4 Slice3

**Fecha:** 2026-08-12. **Decisión:** `proceed` para Slice3, con cero hallazgos
P0/P1/P2. Esta ronda cubre Slice3; el cierre posterior de H4 está documentado
en [`adversarial-h4-gate.md`](adversarial-h4-gate.md) y no autoriza por sí solo
tag ni publicación.

## Alcance revisado

Se auditó la fuente canónica única de los siete schemas (movida al paquete
`epistates/data/schemas/`), el módulo `epistates.schemas` (catálogo cerrado,
inmutable, fail-closed), el CLI `schema list/show`, los recursos de onboarding
(`agent-guide.md`, `minimal-task-card.json`, walkthrough en memoria) y la
integración en `describe --format json`. La revisión comprobó single-source,
determinismo, ASCII puro, ausencia de probing y la invariabilidad de la
frontera de autoridad.

## Contrato

- Una sola fuente normativa para los siete schemas, leída vía
  `importlib.resources` sin checkout; `schemas/` del repo eliminado.
- Catálogo cerrado e inmutable con `sha256` exacto, `validation_scope:
  structural_only`, validador Python normativo, `binding_behavior`,
  `library_authenticates_authority: false`, `authorized_to_execute: false`.
  Accessors devuelven copias/bytes frescos.
- Fail-closed ante recurso ausente, digest divergente, JSON inválido/duplicado,
  no-ASCII e ids `../`/absolutos/`%2e%2e`/Unicode-confusables/Cc. Ningún `$id`
  se abre.
- `schema list --format json` y `schema show <id> --format json` estáticos y
  offline; stdout un único JSON ASCII determinista, exits `0`/`1`(id
  desconocido)/`2`(uso CLI).
- Onboarding empaquetado: guía, artefacto mínimo válido y walkthrough con
  runners en memoria. Ninguno es instrucción ni grant; cada recurso lo declara.
- `task-card.authority`, capability, schema válido, ejemplo o guía nunca cambian
  `provenance_verified: false`, `authority_status: "external_unverified"` ni
  `authorized_to_execute: false`.

## Corrección C1

La primera ronda reprodujo cuatro hallazgos, todos corregidos sin ampliar
alcance:

1. `read_minimal_task_card()` sólo hacía `json.loads` pese a declarar validación.
   Ahora verifica digest → UTF-8 estricto → JSON estricto (sin claves
   duplicadas/NaN/Infinity, raíz objeto) → `validate_task_card` → devuelve una
   copia fresca ya validada.
2. `agent_guide_digest`/`minimal_task_card_digest` sólo recalculaban el hash.
   Se añadieron digests SHA-256 **congelados** y verificación de bytes antes de
   devolver contenido. Fail-closed ante recurso ausente/ilegible, digest
   divergente, UTF-8 inválido y (para JSON) claves duplicadas, NaN/Infinity, raíz
   no objeto y tarjeta semánticamente inválida. Excepción pública estable
   `OnboardingResourceError` con mensajes saneados.
3. Typo «Viger authority» en `agent-guide.md` corregido a «Current authority».
4. El índice Git quedó con siete eliminaciones staged de `schemas/`. Se aplicó
   `git reset HEAD -- schemas/` (reversible); `git diff --cached` quedó vacío y
   las eliminaciones se conservaron como cambios sin stage.

## Evidencia independiente

- `git diff --check`: exit 0; `git diff --cached`: vacío.
- Suite completa contra este worktree con
  `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'`:
  **793 pruebas OK (1 omitida)** — skip pre-existente por socket tmux en
  `test_host_observer`. 75 pruebas focales nuevas (46 `test_schemas.py` +
  29 `test_onboarding.py`); sin regresión de las 718 previas.
- Paridad exacta de los siete ids, digests recomputados contra constantes
  congeladas, mutación agresiva del catálogo/accessors sin contaminación, y
  `schema list/show` byte-identical ASCII estables ante locale/TZ.
- Ataques de id (`../`, absolutos, `%2e%2e`, Unicode confusables, Cc), recurso
  ausente, digest divergente, UTF-8 inválido, JSON con clave duplicada,
  NaN/Infinity, raíz no objeto y tarjeta semánticamente inválida: todos fallan
  cerrados con `OnboardingResourceError`/`SchemaError`.
- Walkthrough con `subprocess`/`socket`/`reloj`/`open` bloqueados: alcanza
  `DONE` de forma determinista; declara no ser sandbox ni prueba de autoridad.
- Wheel de la revisión: 19 módulos `.py` (incluidos `capabilities`, `schemas`, `onboarding`),
  9 package-data (7 schemas + guía + tarjeta mínima), licencia Apache-2.0,
  `Requires-Python: >=3.9`, sin `Requires-Dist`, sin `fixtures/`/`docs/`/
  `tests/`/`schemas/` externos.
- Smoke desde venv limpio y cwd vacío fuera del repo (`env -u PYTHONPATH`):
  import y metadata resueltos desde `site-packages` del venv; versión, help
  (módulo y entrypoint), describe determinista, `schema list/show` (conocido
  `0`/desconocido `1`/uso inválido `2`), `schema_count == 7`,
  `verify_schema_integrity`, tarjeta mínima validada internamente, digests,
  walkthrough determinista, `validate` nominal (`0`/`VALID`) e inválido
  (`1`/`INVALID`), y estabilidad ante locale/TZ/encoding. Autoridad
  autodeclarada nunca produce `provenance_verified`/`authorized_to_execute`
  `true`.

### Evidencia posterior, no parte del veredicto de Slice3

Después de esta decisión independiente, el ejecutor realizó el gate de cierre
H4. Tras la corrección C1 del gate (timestamp pre-H4 obsoleto en el README), se
reconstruyeron dos copias fuente independientes con
`SOURCE_DATE_EPOCH=1786546459` del HEAD `128945f` y se obtuvieron dos wheels
byte-idénticos de `108527` bytes, SHA-256
`921c36ea5d399caa163a7394a1ae6281c28022739b07a8ce34bf929c783aecfe`.
Esta evidencia cierra el riesgo P3 de reproducibilidad, pero no se atribuye al
revisor de Slice3 ni altera retroactivamente el alcance de su veredicto. Véase
[`release-gate.md`](release-gate.md), «Resultado del gate de cierre H4».

## Notas P3 (no bloqueantes)

- Los digests congelados de onboarding se derivan del contenido actual de los
  recursos; si la guía o la tarjeta mínima cambian en un corte futuro, sus
  constantes deben regenerarse (mismo modelo que `epistates.schemas`).
- `build_discovery_document()` lee ahora dos recursos de onboarding vía
  `importlib.resources` para verificar digests en cada llamada. Sigue siendo
  puro y determinista (sin subprocess/socket/reloj/red), pero realiza I/O de
  package-data por invocación, igual que `schema_catalog()`.
- La conformidad semántica de los schemas con un validador JSON Schema externo
  (p. ej. `jsonschema`) no se prueba: los descriptores declaran
  `structural_only` de forma honesta.

## Decisión

`proceed` para H4 Slice3 con cero hallazgos P0/P1/P2. La distribución de
contratos y onboarding es single-source, fail-closed y sin efectos ocultos. El
cierre global posterior está en [`adversarial-h4-gate.md`](adversarial-h4-gate.md);
esta decisión de Slice3 no autoriza por sí sola integración, tag ni publicación.
