# Ronda adversarial — H3 Slice1

**Fecha:** 2026-08-11. **Decisión final de Slice1:** `proceed`.
**H3 completo:** abierto; los cortes operativos no forman parte de esta decisión.

## Alcance

Revisión independiente del contrato neutral `adapter-capabilities/v1`, el
preflight puro, `preflight-result/v1`, sus bindings normativos, CLI, schemas,
fixtures y pruebas. El ejecutor externo implementó en un worktree aislado; el
controlador reprodujo ataques y verificó la evidencia sin aceptar el reporte del
ejecutor como prueba suficiente.

La revisión no cubre observación real mediante Git o `tmux`, entrega literal,
pausa, captura del TUI ni otros subprocess. Esas capacidades continúan fuera de
Slice1 y no quedan autorizadas por este documento.

## Hallazgos corregidos

- preflight incompleto que no ligaba repositorio, worktree/cwd, pane, comando y
  plataforma;
- mezcla entre expectativas del controlador y observaciones inyectadas;
- resultado declarado `ok` que podía conservarse tras adulterar rama, SHA,
  limpieza, pane o plataforma;
- comando esperado y observado vacíos capaces de producir `ok`;
- plataforma no soportada tratada como error no serializable en vez de
  `blocked/platform_unsupported`;
- razones aceptadas fuera del orden canónico;
- resultados legítimos `blocked` por sesión o comando rechazados por el binding;
- supuesto token de plataforma que aceptaba mayúsculas, espacios, barras y
  caracteres de control;
- ejecución de tests desde un venv editable que podía importar el worktree
  principal; el DoD quedó fijado con `PYTHONPATH=src`;
- archivo sonda vacío creado por el ejecutor y retirado antes del cierre.

## Evidencia final

- `PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` → 110 tests, `OK`.
- adaptador `opencode-tmux` válido → `VALID`; plataforma o capability fuera del
  catálogo → `INVALID`.
- `preflight-result` con tarjeta, adaptador, run, attempt, sesión y comando
  exactos → `VALID` mediante el CLI real.
- adulterar rama, SHA, limpieza, pane o plataforma en un resultado `ok` falla
  cerrado durante el binding.
- sesión o comando observados distintos producen un resultado portable
  `blocked`, y ese resultado liga correctamente cuando refleja las expectativas
  externas.
- `windows` produce `blocked/platform_unsupported`; tokens no canónicos fallan
  antes de evaluar.
- `git diff --check` → sin salida; sólo cambiaron rutas autorizadas; no hubo
  commit, push, PR, subprocess del adaptador ni `tmux send-keys` desde el código.

## Riesgo residual aceptado

- el manifiesto declara capacidades, pero no demuestra que estén implementadas;
- las observaciones inyectadas todavía dependen de un host futuro y no son
  atestación por sí mismas;
- JSON Schema expresa la forma portable, mientras el validador Python y el CLI
  son normativos para bindings, orden y coherencia semántica;
- el worktree reutiliza un venv editable externo, por lo que sus verificaciones
  deben fijar `PYTHONPATH=src`;
- H3 no estará cerrado hasta implementar y revisar de manera independiente los
  cortes operativos restantes.
