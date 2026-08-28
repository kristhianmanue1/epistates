# Ronda adversarial — EPI-SKEVI-001

**Fecha:** 2026-08-28. **Base revisada:** `origin/main...6bae5fe`.
**Decisión:** `proceed` para documentación de proceso y el verificador local de
enlaces. Esta decisión no autoriza cambios de runtime, schemas, adaptadores ni
merge de la PR.

## Alcance revisado

- documentación de arquitectura, planes y flujo de desarrollo;
- verificador focal de enlaces Markdown locales y sus pruebas;
- sin cambios a `src/epistates/` salvo lectura de su schema canónico;
- sin incluir los cambios locales preexistentes en `CHANGELOG.md`, `README.md`,
  `docs/release-gate.md` y `src/epistates/_version.py`.

## Hallazgos

- [MED, cerrado] Copiar el gate de planes de Skevi habría interpretado comandos
  entre acentos como rutas y fallado sobre el plan real. Se descartó activarlo y
  se documentó el límite en ADR-0003.
- [MED, cerrado] El primer verificador de enlaces podía evaluar destinos fuera
  del proyecto. Ahora rechaza destinos que escapan de la raíz antes de comprobar
  su existencia; la prueba adversarial cubre `/etc/passwd`.
- [LOW, aceptado] No existe gate automático de estructura de planes. ADR-0003
  lo difiere hasta contar con una sintaxis local y al menos dos planes reales;
  esta ausencia es explícita, no una señal verde implícita.

## Verificaciones

- `git diff --check origin/main...HEAD` → sin errores [pass].
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` → 796
  pruebas en verde, una omitida [pass].
- `python3 scripts/check_documentation_links.py docs/README.md docs/architecture/README.md docs/plans/README.md docs/development-workflow.md docs/architecture/0002-adopcion-limitada-practicas-skevi.md docs/architecture/0003-gate-estructural-de-planes-diferido.md docs/plans/2026-08-28-adopcion-practicas-skevi.md` → siete archivos válidos [pass].
- `git diff --name-only origin/main...HEAD` → sólo los nueve archivos
  declarados por la iniciativa [pass].

## Riesgos residuales

- La baseline local de AN-KLA continúa con el aviso
  `context_target_changed_outside_managed_block`; la verificación de integridad
  es verde, pero el flujo de baseline sigue fuera de este cambio.
- La PR no tiene checks remotos configurados. La evidencia de esta ronda es
  local y reproducible; no se presenta como validación de CI remoto.
