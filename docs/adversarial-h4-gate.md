# Ronda adversarial final — gate de cierre H4

**Fecha:** 2026-08-12. **HEAD auditado:**
`128945fae0db9c9134cc55bef0411510f954484c`. **Decisión final:** `PROCEED`
tras corrección C1, con **cero hallazgos P0/P1/P2**. Esta decisión cierra H4
localmente, pero no autoriza push, tag ni publicación.

## Primera ronda: `FIX-AND-RETRY`

La primera revisión independiente confirmó los claims técnicos centrales del
gate, pero encontró un P2 documental: `README.md` aún usaba
`SOURCE_DATE_EPOCH=1786501546`, correspondiente a la candidata pre-H4. El
comando distribuido construía un wheel reproducible distinto del certificado.

La corrección C1 actualizó el README y el checklist vigente a HEAD `128945f` y
`SOURCE_DATE_EPOCH=1786546459`. Como el README forma parte de `METADATA`, se
reconstruyó y recertificó el wheel; no cambió código runtime.

## Evidencia independiente C1

- Suite: `793` pruebas en verde, `1` omitida por la dependencia local de
  Git/tmux/socket del test de observación real.
- Dos copias fuente nuevas e independientes, construidas sin red ni
  dependencias con `SOURCE_DATE_EPOCH=1786546459`, produjeron wheels
  byte-idénticos de `108527` bytes.
- SHA-256 certificado:
  `921c36ea5d399caa163a7394a1ae6281c28022739b07a8ce34bf929c783aecfe`.
- El comando operativo del README reprodujo exactamente ese tamaño, hash y
  contenido; no sólo se comprobó igualdad entre las dos construcciones.
- Wheel: `34` entradas, `19` módulos Python, `9` recursos empaquetados
  (7 schemas, guía y tarjeta mínima), licencia y metadata; sin dependencias de
  runtime ni activos externos del repositorio.
- Instalación en venv nuevo, desde cwd vacío y sin `PYTHONPATH`, resolvió
  `epistates` desde `site-packages`; versión runtime y metadata: `0.1.0a1`.
- Smoke instalado: versión, ayudas, `describe`, `schema list/show` con exits
  `0/1/2`, integridad, onboarding, walkthrough y validación nominal/adversarial.
- Ataques de ids, JSON y autoridad autodeclarada fallaron cerrados; las
  superficies estáticas no realizaron probing de subprocess, socket, red,
  reloj, Git, tmux ni tamaño de terminal.
- Estado final: nada staged, `git diff --check` limpio y ningún artefacto de
  build dentro del worktree.

## Riesgos residuales aceptados

- Los schemas declaran honestamente `structural_only`; no se certifica
  equivalencia semántica con un validador JSON Schema externo.
- Gate ejecutado en macOS con Python 3.9; Linux no se probó en este corte y
  Windows permanece no soportado.
- `.gitignore` no incluye `build/`/`dist/`; el gate evitó y comprobó esos
  artefactos, pero la mejora de higiene queda para otro corte.

## Decisión

`PROCEED`: cero hallazgos P0/P1/P2. H4 queda cerrado localmente y el commit de
integración puede prepararse con autoridad del mantenedor. Push, tag, GitHub
Release y publicación siguen requiriendo autorizaciones separadas.
