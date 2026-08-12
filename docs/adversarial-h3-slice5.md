# Ronda adversarial — H3 Slice5

**Fecha:** 2026-08-11. **Decisión:** `proceed` para Slice5.
**H3 completo:** cerrado tras la integración pendiente de este corte.

## Alcance revisado

Se auditó el puente puro `review-evidence/v1` → `audit-result/v1` →
`apply_audit`, sus bindings de cadena, evidencia, decisión, autoridad y tiempo,
la ampliación pre-release de `audit-result/v1` y el CLI de validación. La ronda
no autoriza commit, push, PR, tag ni release.

## Hallazgos y correcciones

La primera ronda reprodujo tres bloqueadores:

- un `observed_at` autodeclarado del año 2099 pasaba el binding;
- retirar `review_evidence_digest` permitía degradar parcialmente un artefacto
  bridge y alcanzar `DONE` mediante el camino H2;
- el grant se correlacionaba con la tarjeta, pero no se contrastaba con una
  expectativa externa vigente.

También se corrigió una afirmación de compatibilidad incorrecta: los
validadores v1 anteriores rechazan el nuevo campo del bridge.

La corrección añadió timestamp exacto y política externa de frescura acotada,
grant externo exacto, bidireccionalidad estructural entre `capture` y
`review_evidence_digest`, pruebas de cero llamadas a `apply_audit` ante fallo y
documentación honesta de la ampliación pre-release.

## Evidencia independiente

- `git diff --check`: exit 0.
- Suite completa contra el worktree: 572 pruebas correctas, una omitida.
- `observed_at=2099-01-01T00:00:00Z`: rechazado por exceder la edad máxima de
  auditoría.
- Eliminación sólo de `review_evidence_digest`: rechazada porque la evidencia
  `capture` lo exige.
- `expected_grant_id` distinto: rechazado por no coincidir con la autoridad de
  la tarjeta.
- Camino nominal con review, decisión, autoridad y tiempo ligados: `DONE`, con
  digest exacto del `review-evidence`.
- CLI nominal del artefacto bridge con la cadena completa: `VALID`.
- El módulo del puente no contiene subprocess, captura tmux, envío de teclas,
  lectura del reloj ni apertura de archivos.
- Schemas y fixtures JSON son sintácticamente válidos.

## Riesgos residuales aceptados para el corte

- El puente es stateless; la prevención global de replay requiere persistir
  externamente run, attempt, digest de review y estado.
- Los parámetros de decisión, autoridad y timestamp son inyectados por el
  controlador. El contrato comprueba correlación exacta, no atestación
  criptográfica de su procedencia.
- El validador nuevo sigue leyendo artefactos H2 puros. Retirar simultáneamente
  todos los campos bridge crea otro artefacto H2 válido; por ello un host H3
  debe usar exclusivamente `apply_audit_from_review`, no `apply_audit` legado.
- La ampliación ocurrió antes de la primera release: los artefactos bridge no
  son aceptados por validadores v1 anteriores a Slice5.

## Decisión

`proceed` para H3 Slice5. La cadena de inspección sólo alcanza la transición de
auditoría cuando evidencia, decisión, autoridad, tiempo e identidad están
ligados a expectativas externas. Con Slice1–Slice5 aceptados, H3 queda cerrado
funcionalmente; integración Git y preparación de release requieren autoridad
separada.
