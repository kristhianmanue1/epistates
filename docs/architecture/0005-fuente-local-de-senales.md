# ADR-0005 — Fuente local de señales no confiables

**Estado:** aceptado. **Fecha:** 2026-08-28. **Depende de:** ADR-0004.

## Decisión

La primera fuente candidata es una bandeja local por ejecución, publicada por
archivo temporal y `rename` dentro del mismo filesystem. La bandeja es una
entrada no confiable: sólo puede alimentar `SignalReceiptStore`; nunca cambia
estado, inicia inspección, despierta tareas, llama a `tmux` o concede autoridad.

Antes de publicar, el productor escribe un JSON estricto y acotado, sincroniza
el archivo, renombra atómicamente y sincroniza el directorio. El consumidor usa
descriptores de directorio/archivo y rechaza symlinks, no-regulares, rutas fuera
de la bandeja, contenido libre, JSON inválido y archivos sobre el límite.

## Recuperación y disponibilidad

Los eventos del sistema de archivos son avisos, no evidencia durable. En cada
inicio el futuro watcher deberá reconciliar el directorio completo antes de
esperar eventos. El sistema aplica cuota de bytes y archivos por ejecución,
límite de tasa, tamaño máximo, cuarentena de entradas inválidas y diagnóstico
saneado. Un proceso del mismo usuario puede falsificar una señal; el resultado
permitido sigue siendo sólo `invalid`, `duplicate`, `expired` o una aceptación
que requiere validación independiente posterior.

## No decisión

Esta ADR no elige API de wake, kqueue, inotify, polling, daemon ni soporte
multiplataforma. Tampoco autoriza implementar watcher o reactivación.
