# Ronda adversarial — E3a store de recibos

**Fecha:** 2026-08-28. **Decisión:** `proceed`.

## Alcance

Se revisó exclusivamente `SignalReceiptStore`: consumo SQLite local, sin watcher,
red, CLI, wake, `tmux` ni reactivación.

## Hallazgos corregidos

- Identidades con el delimitador de clave podían colisionar; ahora IDs y digest
  tienen formato cerrado antes de construir la clave.
- El store no exigía `WAITING_EXTERNAL`; ahora rechaza cualquier otro estado.
- Faltaba prueba de replay tras reinicio; una segunda instancia SQLite devuelve
  `duplicate`.
- Se añadieron regresiones para digest adulterado y corrupción del store.

## Evidencia

- Pruebas focales: 7 correctas en Python 3.9 y Homebrew Python 3.12.
- Suite completa: 803 correctas, 1 omitida, en Python 3.12.
- `git diff --check`: correcto antes del cierre.

## Riesgos residuales y límites

- El kill switch es un parámetro inyectado; no es todavía un control-plane
  persistente.
- No hay limpieza/retención automatizada ni fuente de señal.
- Un store local no autentica la fuente de la señal ni autoriza inspección.

## Decisión

`proceed` para cerrar E3a como store local de consumo único. E3b watcher sigue
bloqueado hasta que el mantenedor defina una fuente permitida y autorice una
tarjeta separada.
