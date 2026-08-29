# Ronda adversarial — permisos efectivos OpenCode E4-N

Fecha: 2026-08-28

Tarjeta: `e4-opencode-effective-permissions`

Decisión: **PROCEED para la validación interna E4-N; NO PROCEED para activación
o wake real.**

## Ataques requeridos

- agente ausente, duplicado, modo o modelo incorrectos;
- ruleset ausente, enorme, mal tipado o con controles;
- deny global ausente o seguido por allow/ask de herramienta;
- external allow wildcard, duplicado, relativo, traversal o sufijo falso;
- excepción interna antes/después del deny y defaults hostiles anteriores;
- respuesta hostil que lanza durante comparación;
- prueba de integración que garantice cero POST cuando capabilities falla.

## Veredicto

## Evidencia y correcciones

- `OpenCodeWakePort` queda ligado exactamente a OpenCode `1.18.25`.
- `capabilities()` exige un agente único, `primary`, modelo
  `zai/<model_id>` exacto y ruleset acotado de hasta 256 reglas.
- La política busca el último deny global y valida un tail cerrado: vacío,
  external deny, o external deny seguido de una única excepción absoluta de
  truncado con sufijo `/opencode/tool-output/*`.
- Defaults allow/ask anteriores al deny se aceptan como reglas superadas; una
  reapertura posterior de cualquier herramienta falla cerrada.
- Paths relativos, traversal, controles, wildcard external allow, sufijos
  falsos, duplicados y estructuras desconocidas fallan cerrados.
- Una prueba de integración invoca `request_wake()` con `read -> allow` tardío
  y comprueba `unsupported` y cero POST.

La primera suite completa reveló que `opencode_observer` importaba el patrón
privado `_VERSION` retirado durante el binding exacto. Se restauró el símbolo
para compatibilidad interna sin relajar el constructor. Una segunda corrida
focal reveló una fixture HTTP con el agente mínimo antiguo; se actualizó la
tarjeta y la fixture al contrato efectivo. No se ocultaron ni normalizaron esos
fallos.

## Resultado de ataques

| Ataque | Resultado |
| --- | --- |
| Ausente, duplicado, modo/modelo/proveedor distinto | `unsupported`. |
| Ruleset ausente, mal tipado, enorme o con controles | `unsupported`. |
| Sin deny global o allow/ask de herramienta posterior | `unsupported`; cero POST. |
| External wildcard allow, relativo, traversal o sufijo distinto | `unsupported`. |
| Defaults hostiles antes del deny + excepción interna única | `supported`; los defaults quedan superados por última coincidencia. |
| Versión distinta de 1.18.25 | constructor o health fail-closed. |

## Checks finales

- Tarjeta: `VALID`.
- Pruebas focales wake/delivery/observer/HTTP: 49, `OK`.
- Suite completa: 891 pruebas, `OK (skipped=1)`.
- `git diff --check`: limpio.
- Sin red, servidor, credenciales, sesión, prompt o wake real.

## Veredicto

`PROCEED` para integrar y versionar E4-N como validación interna. La política
resuelve el falso bloqueo de E4-M sin aceptar reaperturas de herramientas. Esto
no autoriza wiring runtime: antes de un wake real aún se requiere una tarjeta
separada, preflight sobre el artefacto final, kill switch activo, reserva/ledger
y revisión adversarial del flujo completo.
