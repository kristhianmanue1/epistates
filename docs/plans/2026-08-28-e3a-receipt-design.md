# Propuesta E3a — contrato de recibo y consumo local

**Estado:** propuesta de diseño; no es un schema ni API implementados. **Plan:**
[`EPI-E3-001`](2026-08-28-e3-senal-local.md). **Decisión de alcance:**
[`ADR-0004`](../architecture/0004-senal-local-y-consumo-atomico.md).

## Invariante

Una señal sólo puede habilitar una inspección única y read-only cuando queda
consumida atómicamente para el contexto exacto de una ejecución en
`WAITING_EXTERNAL`. No prueba finalización, corrección, autoridad ni permiso
para dispatch, corrección, aceptación o mutación Git.

## Candidato de recibo

El futuro contrato `epistates/local-signal-receipt/v1` deberá contener sólo:

| Campo | Regla propuesta |
|---|---|
| `task_id`, `run_id`, `attempt_id` | Coinciden exactamente con el contexto activo externo. |
| `adapter_id`, `session_name` | Coinciden con el adaptador y sesión esperados. |
| `dispatch_receipt_digest` | Digest exacto del dispatch que derivó `WAITING_EXTERNAL`. |
| `event_type` | Valor de catálogo cerrado; inicialmente sólo una finalización externa. |
| `received_at` | Tiempo observado e inyectado por el límite local, nunca hora declarada por la señal. |
| `expires_at` | Derivado de política externa de TTL, no controlado por la señal. |
| `outcome` | `accepted`, `duplicate`, `expired`, `invalid` o `disabled`. |
| `receipt_id` | Identificador local opaco; no contiene prompt, captura, comando, credencial ni texto libre. |

No se acepta todavía una fuente concreta ni un identificador aportado por un
emisor. La clave de consumo inicial es la tupla cerrada
`(task_id, run_id, attempt_id, dispatch_receipt_digest, event_type)`; una
segunda señal equivalente es `duplicate` aunque llegue por otra ruta.

## Operación atómica propuesta

La frontera futura recibirá artefactos ya ligados por los validadores actuales y
un contexto externo con estado esperado `WAITING_EXTERNAL`. Sólo después de
validar identidad, digest y política podrá llamar a una operación conceptual:

```text
consume_once(validated_context, observed_now, policy) -> receipt
```

La operación deberá ser linealizable por clave de consumo: ante dos callers o
un retry concurrente, exactamente uno puede devolver `accepted`; los demás
devuelven `duplicate`. Una reserva parcial debe ser recuperable tras crash sin
convertirse en una segunda aceptación. El mecanismo concreto (archivo, SQLite u
otro store) queda sin decidir y no debe introducirse en esta tarea.

## Tiempo, expiración y reinicio

- La fuente de señal no aporta tiempo confiable. El límite local inyecta
  `received_at` y calcula `expires_at` con una política externa acotada.
- El store conserva el recibo aceptado y su clave durante al menos la ventana
  de TTL más la ventana de replay definida por la futura política; eliminarlo
  antes reabre el replay.
- Si tras restart el reloj observado retrocede respecto del registro persistido,
  no se infiere validez: se devuelve `disabled` y requiere intervención del
  mantenedor.
- Corrupción, lectura incompleta o estado de reserva ambiguo fallan cerrados;
  no se reconstruye un recibo aceptado a partir de la señal entrante.

## Resultado y transición

`accepted` sólo crea una solicitud para una inspección única; no ejecuta esa
inspección. El controlador conserva la responsabilidad de revalidar la cadena
de tarjeta, preflight, dispatch y aviso antes de `REVIEWING`. `duplicate`,
`expired`, `invalid` y `disabled` no producen llamada al runner, dispatch ni
transición de estado.

## Matriz de escenarios que deberá convertirse en fixtures

| Escenario | Resultado requerido | Efectos permitidos |
|---|---|---|
| Primera señal ligada al contexto activo | `accepted` | Registrar consumo y solicitar inspección. |
| Misma señal tras éxito o restart | `duplicate` | Ninguno. |
| Dos callers concurrentes | Un `accepted`, resto `duplicate` | Una sola solicitud. |
| Digest, sesión o intento de otra ejecución | `invalid` | Ninguno. |
| Llega después de TTL | `expired` | Ninguno. |
| Store corrupto, reserva ambigua o reloj regresivo | `disabled` | Ninguno; conservar diagnóstico saneado. |
| Kill switch vigente | `disabled` | Ninguno; no consumir como éxito. |

## Límites y paradas

Esta propuesta no decide formato persistente, lock, fuente de señal, API de wake
ni reactivación. Se detiene y requiere ADR/autoridad nueva si la implementación
necesita red, credenciales, una API privada, contenido libre, dependencia nueva,
cambio de contratos v1 o cualquier efecto sobre Git, `tmux` o dispatch.
