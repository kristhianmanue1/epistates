# Ronda adversarial — E3b lector de bandeja

**Fecha:** 2026-08-28. **Decisión:** `proceed`.

## Alcance

Se revisó sólo la reconciliación local de archivos. No se evaluaron watcher de
eventos, wake, red, `tmux` ni reactivación.

## Hallazgos y correcciones

- Symlink/TOCTOU: lectura por descriptor con `O_NOFOLLOW` y `fstat`.
- JSON inválido, no-regulares y archivos grandes: rechazados.
- Starvation: entradas inválidas se cuarentenan con `os.replace`; un lote
  posterior puede alcanzar una señal válida.
- Replay: el store subyacente conserva consumo único tras restart.

## Evidencia

- Pruebas focales del inbox: 4 correctas.
- Suite completa: 807 correctas, 1 omitida, Python 3.12.
- Árbol y remoto limpios tras `cf79938`.

## Riesgos residuales

- La cuarentena no tiene aún cuota de retención ni política de colisión.
- No hay mecanismo de eventos; la reconciliación se invoca explícitamente.
- `disabled` conserva la entrada para intervención, lo que puede requerir
  operación humana ante un store dañado.

## Decisión

`proceed` para el lector acotado. El siguiente slice requiere una tarjeta
separada para un adaptador de eventos de filesystem y no puede despertar ni
ejecutar inspección.
