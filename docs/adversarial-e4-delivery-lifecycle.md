# Ronda adversarial — ciclo durable de entrega E4

Fecha: 2026-08-28

Tarjeta: `e4-delivery-lifecycle`

Decisión: **PROCEED sólo para diseño; implementación y wake bloqueados.**

## Ataques

| Ataque | Resultado |
| --- | --- |
| Crash después de enviar y antes de guardar `submitted` | `submitting` queda durable; sin idempotencia/consulta inequívoca pasa a `ambiguous`, nunca a retry. |
| HTTP `204` pero proveedor sin saldo | Permanece `submitted` hasta observar fallo terminal; jamás se promueve por tiempo o presencia de assistant. |
| Assistant vacío interpretado como respuesta | Rechazado: `completed` exige condición terminal pública, contenido no vacío cuando el contrato lo requiera y binding a la entrega. |
| Dos reconciliadores actualizan el mismo intento | CAS sobre estado esperado: sólo una transición gana; la otra relee sin efecto. |
| Fallo terminal libera cuota para reintentar | Rechazado: nonce y cuota siguen consumidos; otro intento necesita decisión y nonce nuevos. |
| Reconciliación se convierte en sender | Prohibido por contrato: sólo inspecciona y transiciona; no llama `prompt_async`. |
| Respuesta exitosa concede autoridad posterior | Rechazado: `completed` sólo acredita entrega, no corrección, ejecución, aceptación ni permiso. |
| Logs conservan prompt, respuesta o credencial | El ledger guarda digests, clases saneadas y referencias opacas mínimas. |

## Hallazgos

1. Los cuatro estados inicialmente propuestos no cerraban la ventana de crash
   antes del acuse. Se añadió `submitting`.
2. Tratar todo timeout como `failed` permitiría retry inseguro. Se mantiene
   `ambiguous` como terminal para el nonce.
3. El ledger de cuotas/nonces y el ledger de entrega tienen responsabilidades
   distintas; compartir transacción puede ser deseable, pero fusionar semántica
   ocultaría si hubo autorización, I/O o finalización.
4. La API OpenCode observada no basta todavía como contrato terminal estable;
   su forma y binding deben caracterizarse en una tarea separada.

## Condiciones para implementar

- tarjeta nueva con schema/almacenamiento explícitos;
- transiciones CAS y pruebas de concurrencia, crash y restart;
- ninguna red ni proveedor en la primera implementación;
- revisión adversarial fresca antes de integrar `WakeGuardStore`;
- autorización separada para reconciliador, OpenCode real y wake.
