# Ronda adversarial — E3b adaptador kqueue

**Fecha:** 2026-08-28. **Decisión:** `proceed`.

## Alcance revisado

Se revisó `KqueueSignalAdapter` en macOS: una espera sobre el directorio local
que llama al reconciliador inyectado una vez y desecha su retorno. No se revisó
ni se habilitó E4, wake, inspección, `tmux`, red, daemon, polling, hilos o
reactivación.

## Ataques y resultados

| Ataque | Resultado comprobado |
| --- | --- |
| Evento coalescido o flood | `control(..., 1, ...)` entrega sólo una pista y se llama una vez a `reconcile`; no se interpreta su retorno. |
| Evento perdido / reinicio | El timeout no sustituye la reconciliación de arranque; dos adaptadores nuevos no comparten estado de eventos. |
| Directorio borrado o descriptor revocado | El error se convierte solamente en una petición de reconciliación fail-closed; no hay permiso ni acción. |
| Permisos denegados | La creación falla cerrada sin invocar `reconcile`. |
| Retorno engañoso del reconciliador | Un retorno `False` no cambia el `True` de la pista: el adaptador no traduce outcomes a autorización. |

## Frontera verificada

El módulo sólo abre el directorio, configura `kqueue`, espera una vez y llama al
callback. No recibe payload de evento, no lee el contenido de bandeja, no
importa `tmux` ni red, y no expone API de wake. La aceptación/duplicado/expirado
permanece exclusivamente en `SignalReceiptStore` y la lectura en
`LocalSignalInbox`.

## Riesgos residuales

- La pérdida de eventos sigue siendo posible por diseño; la reconciliación al
  arranque es obligatoria y los eventos son sólo pistas.
- La cuarentena del lector conserva sus riesgos ya aceptados de cuota y colisión;
  este adaptador no los modifica.
- `kqueue` es deliberadamente macOS-only. Linux y Windows no obtienen fallback.

## Evidencia

- Tarjeta `e3b-kqueue-adapter`: `VALID`.
- Pruebas focales y suite Python 3.12: 814 correctas, 1 omitida.
- Enlaces locales y `git diff --check`: correctos.

## Decisión

`proceed`: E3b queda listo como detección local + reconciliación local, siempre
que el controlador reconcilie al arranque y nunca convierta el booleano de pista
en wake, inspección, permiso o acción.
