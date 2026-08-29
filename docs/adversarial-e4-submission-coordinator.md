# Ronda adversarial — coordinador durable de submission E4

Fecha: 2026-08-28

Tarjeta: `e4-submission-coordinator`

Decisión: **PROCEED para submission local con puerto inyectado; transporte
productivo, reconciliación y wake automático bloqueados.**

## Ataques y resultado

| Ataque | Resultado |
| --- | --- |
| Llamar sin reserva exacta del guard | `not_found` o `mismatch`; no cambia el ledger ni llama al puerto. |
| Sustituir proveedor, versión, agente, modelo o cuerpo | El binding completo difiere; no se entra en `submitting`. |
| Mutar configuración del puerto OpenCode entre binding y cuerpo | Sus propiedades de binding son read-only y el cuerpo usa los mismos valores privados ligados al digest. |
| Activar kill switch entre CAS y puerto | La segunda lectura lo detecta; `submitting → failed` con evidencia pre-I/O y cero llamadas. |
| Dos controladores compiten por el mismo nonce | El CAS `reserved → submitting` tiene un ganador y se observa exactamente una llamada. |
| El puerto lanza, devuelve `failed`, un tipo desconocido o un objeto hostil | Termina `ambiguous`; no escapa excepción ni se habilita retry. |
| `queued` se presenta como finalización | Sólo produce `submitted`; nunca `completed`. |
| Falla persistir el acuse después de llamar | El método devuelve `ambiguous`, el estado durable queda `submitting` y un reinicio no reenvía. |
| Tipos inválidos llegan a la relectura del guard | Resultado cerrado `invalid`; no excepción. |
| La prueba integrada usa red real | Rechazado: `OpenCodeWakePort` recibe un transporte falso en memoria; no se abre socket ni se inicia servidor. |

## Hallazgos corregidos durante la ronda

1. Las versiones OpenCode con puntos requerían un patrón separado del ID de
   sesión; `1.18.23` quedó aceptado y ligado exactamente al health simulado.
2. Un resultado externo con `__eq__` hostil podía lanzar durante su
   clasificación; ahora sólo se comparan strings.
3. La configuración pública mutable del puerto permitía TOCTOU entre el digest
   y el cuerpo; ahora las propiedades relevantes son de sólo lectura.
4. `submitting → failed` se habilitó sólo para una precondición durable que
   prueba cero llamadas. Tras intentar el puerto, la incertidumbre termina en
   `ambiguous`.

## Riesgos residuales y stop rules

- No existe transacción distribuida entre SQLite y un futuro HTTP: el kill
  switch aún puede cambiar después de la última lectura y antes del I/O. La
  ventana se minimiza, no se elimina.
- Un proceso local comprometido puede omitir el coordinador y llamar al puerto;
  esta primitiva no es sandbox ni atestación.
- El digest del cuerpo liga el objeto JSON canónico, no los bytes de una futura
  serialización HTTP.
- `submitted` sólo acredita el acuse del puerto. Falta un reconciliador
  read-only para observar `completed`, `failed` o `ambiguous` terminal.
- No se probaron red, credenciales, saldo Z.ai, sesión real, prompt real ni
  respuesta del modelo. No existe retry ni liberación de cuota.

## Evidencia de cierre

- tarjeta `task-card/v1`: válida;
- pruebas focalizadas de guard, ledger, puerto y coordinadores: verdes;
- suite completa: 852 pruebas OK, con un skip preexistente;
- comprobación de enlaces documentales y `git diff --check`: verdes;
- cambios limitados a las doce rutas de la tarjeta.

El veredicto no concede autoridad para transporte de producción, red,
credenciales, reconciliación, wake real o automático, API pública, commit,
push ni release.
