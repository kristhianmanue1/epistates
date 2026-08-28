# ADR-0006 — Adaptador kqueue local de una espera

**Estado:** aceptado. **Fecha:** 2026-08-28. **Depende de:** ADR-0004 y
ADR-0005.

## Decisión

E3b usa exclusivamente en macOS un adaptador `kqueue` sobre el descriptor del
directorio de bandeja. `KqueueSignalAdapter.wait_once()` espera una sola vez;
ante una pista de cambio llama exclusivamente al reconciliador inyectado y
descarta su retorno. Sólo devuelve `True` para indicar que hubo una pista (o
que el descriptor dejó de poder observarse y debe reconciliarse fail-closed), y
`False` ante timeout.

El controlador debe invocar `LocalSignalInbox.reconcile()` al arrancar, antes de
esperar eventos. Los eventos pueden perderse o coalescerse; nunca son fuente de
verdad ni permiso. El adaptador no contiene bucle, hilo, daemon, polling,
payload, interpretación de outcomes, wake, inspección, `tmux`, red ni
reactivación.

## Consecuencias

- Un flood o varios eventos coalescidos producen a lo sumo una reconciliación
  por `wait_once`; el límite de lote corresponde al reconciliador.
- Un directorio borrado, descriptor revocado o error operativo pide una única
  reconciliación; ésta puede devolver `disabled`, sin mutar ni reactivar nada.
- Si el directorio no puede abrirse (incluidos permisos), no se crea el
  adaptador y el controlador debe tratarlo como indisponibilidad local.
- Linux y Windows fallan explícitamente: no se simulan ni se sustituyen por
  polling.

## No decisión

Esta ADR no diseña E4 ni una interfaz de wake, rate limit, kill switch
persistente o reactivación. Todos requieren autoridad y threat model separados.
