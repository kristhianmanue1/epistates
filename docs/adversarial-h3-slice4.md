# Ronda adversarial — H3 Slice4

**Fecha:** 2026-08-11. **Decisión:** `proceed` para Slice4.
**H3 completo:** abierto; clasificación `OK`/`PARCIAL`/`BLOQ` y aplicación de
auditoría siguen fuera de este corte.

## Alcance revisado

Se auditó el aviso humano cerrado `epistates/human-notice/v1`, la frontera
read-only `ReviewRunner`/`TmuxReviewRunner`, la orquestación de captura y checks
una sola vez, `epistates/review-evidence/v1`, sus bindings y el CLI. La revisión
no autoriza commit, push, PR, gateway, polling, watcher ni automatización.

## Hallazgos y correcciones

La primera ronda reprodujo dos bloqueadores materiales:

- el binding aceptaba evidencia sin el check `unit_tests` requerido por la
  tarjeta;
- el runner de producción omitía `PYTHONPATH`, por lo que ejecutaba la suite
  contra el checkout principal en vez del worktree inspeccionado.

También detectó que el entorno mínimo de Git fallaba en macOS por el warning de
`confstr`, que `capture-pane` omitía el `-J` documentado, que `diff_check` no
cubría staged + unstaged y que resultados inválidos de un runner inyectado
podían entrar en el recibo.

La corrección exige igualdad exacta del conjunto de checks, liga
`PYTHONPATH=<worktree>/src` sin heredar el entorno hostil, fija `TMPDIR=/tmp`,
endurece Git (`core.fsmonitor=false`, configuración global/sistema excluida y
`--no-ext-diff --check HEAD --`), añade `-J`, valida completamente cada outcome
y valida el documento ensamblado antes de retornarlo.

## Evidencia independiente

- `git diff --check`: exit 0.
- Suite completa contra este worktree: 478 pruebas correctas, una omitida.
- Smoke real de `TmuxReviewRunner` en macOS, sin ejecutar otra captura:
  `git_status`, `diff_check` y `unit_tests` devolvieron `pass`.
- El check real de tests produjo salida de 590 bytes, consistente con la suite
  de 478 pruebas de este worktree.
- Reproducción externa con `unit_tests` eliminado: rechazada con
  `checks no coinciden exactamente con los requeridos por la tarjeta`.
- La única captura post-ejecución autorizada encontró la marca exacta
  `FIN H3-SLICE4-CORRECTION1`.
- Los schemas y fixtures JSON son sintácticamente válidos.

## Riesgos residuales aceptados para v1

- La unicidad global del aviso es stateless y depende de persistir externamente
  `(run_id, attempt_id, event_id, estado)`; mentir sobre el estado permitiría
  presentar otra vez el mismo aviso.
- El recibo conserva digests, longitudes y estados, no stdout/stderr ni el texto
  capturado; la clasificación humana pertenece al siguiente corte.
- `max_output_bytes` se aplica después de que `subprocess.run` captura la salida;
  no constituye aislamiento de memoria del sistema operativo.
- `git_status` con exit 0 es evidencia aun cuando el worktree esté sucio; esa
  suciedad queda representada por digest y longitud, no clasificada en Slice4.
- `capture_lines` queda atestiguado por el runner confiable y limitado a
  `[1, 200]`; v1 no añade una política externa separada para ese valor.

## Decisión

`proceed` para H3 Slice4. La implementación liga aviso, cadena de autoridad,
estado y frescuras antes de efectos; realiza una sola captura y cada check una
sola vez; y falla sin reintento ante resultados indeterminados. Esta decisión
no cierra H3 ni autoriza commit o publicación.
