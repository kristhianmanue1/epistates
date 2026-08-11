# Ronda adversarial — H3 Slice2

**Fecha:** 2026-08-11. **Decisión:** `proceed` para Slice2.
**H3 completo:** abierto; entrega literal, pausa sin polling e inspección única
siguen fuera de este corte.

## Alcance revisado

Se auditó el runner read-only `ProductionHostRunner`, el protocolo inyectable
`HostRunner` y `observe_opencode_tmux`. La revisión comprobó que el corte sólo
observa Git y tmux mediante operaciones cerradas y que no autoriza, entrega
instrucciones ni captura contenido del pane.

## Hallazgos y correcciones

La primera ronda encontró nueve casos que debían fallar cerrado: estado Git
compuesto sólo por whitespace, timeouts no finitos o fuera de rango, más de un
LF final, stderr con exit cero, herencia de entorno hostil, errores `OSError`
no saneados, timestamps imposibles, tarjetas globalmente inválidas y controles
en los campos del pane. Todos quedaron corregidos con regresiones específicas.

El primer smoke contra tmux real descubrió un décimo defecto: tmux 3.6a
sustituye un TAB literal del formato por `_`, por lo que el framing original no
producía tres campos. Se cambió a un separador printable `|`; cualquier colisión
produce una cantidad inesperada de campos y se rechaza, sin interpretación
ambigua. La corrección tiene regresiones para la forma real, la forma antigua y
colisiones en comando o ruta.

## Evidencia independiente

- `git diff --check`: exit 0.
- Suite completa ejecutada contra este worktree con
  `PYTHONPATH=src /Users/krisnova/www/aria/epistates/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`:
  209 pruebas correctas; un smoke portable omitido dentro del sandbox al no
  poder acceder al socket tmux.
- Smoke independiente fuera del sandbox con `/usr/bin/git` y
  `/opt/homebrew/bin/tmux`: observó rama `codex/h3-host-observer`, SHA
  `5a6cc0478212c167cc1ff59a4d44bbf92a4926f8`, sesión viva, comando `opencode`
  y cwd `/private/tmp/epistates-h3-slice2`. El preflight devolvió `blocked`
  únicamente con `dirty`, resultado esperado para cambios aún sin commit.
- Reproducciones adversariales independientes confirmaron entorno mínimo sin
  variables hostiles, bloqueo de stderr con exit cero, timestamps imposibles,
  tarjetas inválidas, timeout NaN/infinito, LF doble, controles tmux y estado
  Git compuesto sólo por whitespace.

## Riesgos residuales aceptados para v1

- `observed_repository` es el basename del toplevel. En worktrees cuyo nombre
  físico difiera del repositorio lógico, el controlador debe modelar esa
  identidad explícitamente o el preflight bloqueará con
  `repository_mismatch`. Resolver identidad desde el common-dir o una fuente
  más fuerte queda para un corte posterior antes del cierre integral de H3.
- `max_output_bytes` se comprueba después de que `subprocess.run` captura la
  salida; limita interpretación y devolución, pero no constituye aislamiento
  de memoria del proceso hijo.
- Una ruta o comando tmux que contenga `|` se rechaza. Es una restricción
  fail-closed deliberada del adaptador v1.

## Decisión

`proceed` para H3 Slice2: la observación real es cerrada, determinista y falla
de forma segura ante entradas o salidas ambiguas. Esta decisión no cierra H3 ni
autoriza commit, push, PR, entrega de instrucciones o publicación.
