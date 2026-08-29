# Ronda adversarial — E4-I reconciliador terminal

**Fecha:** 2026-08-28. **Artefacto:** implementación local no publicada.
**Veredicto:** **PROCEED únicamente para reconciliación simulada e interna.**
Observador productivo, red, credenciales, reintento, wake real, API pública,
commit, push y release permanecen bloqueados.

## Alcance revisado

- `WakeTerminalReconciler`, `TerminalObserver` y `TerminalObservation`;
- transiciones desde `submitting` y `submitted` en el ledger durable;
- binding exacto, reinicio, concurrencia, respuestas inconsistentes y ausencia
  de capacidades de envío.

No se invocó proveedor, sesión, endpoint, prompt ni transporte real.

## Ataques y resultado

| Ataque | Resultado observado |
|---|---|
| Reconciliar `reserved` como permiso implícito | Se devuelve `conflict`; no se consulta al observador ni se envía. |
| Reiniciar con estado `submitting` sin request id ligado | Termina `ambiguous` sin consultar al proveedor; nunca reenvía. |
| Sustituir proveedor, versión, agente, modelo o cuerpo | El binding completo difiere; no se observa ni transiciona. |
| Devolver destino o digest de cuerpo cruzado | El intento termina `ambiguous`; nunca se atribuye el resultado ajeno. |
| Confundir `pending` con entrega completa | Se conserva `submitted` sin evento nuevo ni liberación de cuota. |
| Declarar `completed` sin texto no vacío | Termina `ambiguous`; un assistant vacío no acredita entrega. |
| Incluir partes de herramienta, aun diciendo `pending` o con texto | Termina `failed`; tools domina sobre la clasificación declarada. |
| Lanzar excepción o devolver un objeto no contractual | Termina `ambiguous`; la excepción no escapa ni habilita retry. |
| Ejecutar dos reconciliadores simultáneos | Ambos pueden leer, pero el CAS permite una sola transición terminal. |
| Reconciliar de nuevo un estado terminal | Devuelve el estado durable sin volver a observar. |
| Introducir envío a través del puerto de observación | El protocolo sólo expone binding y `observe`; una prueba AST prohíbe imports comunes de red/subprocess y verifica que no exista `request_wake`/`send`. |
| Usar contenido del proveedor como instrucción | La observación sólo acepta booleanos, clases cerradas y digests; no conserva texto, prompt ni errores libres. |

## Hallazgo corregido durante la ronda

La primera versión evaluaba `pending` antes de `has_tool_parts`. Una observación
contradictoria podía mantener el intento abierto aunque revelara ejecución de
herramientas. Se invirtió la precedencia y se añadió una regresión específica:
cualquier tool part produce `failed`, incluso si el proveedor declara
`pending`.

## Riesgos residuales y condición de parada

1. `TerminalObserver` es una abstracción inyectada, no una integración
   productiva. Su futura implementación necesita API pública documentada,
   autenticación y threat model propios.
2. El ledger no conserva request id público. Por ello, `submitting` se cierra
   deliberadamente como `ambiguous`; resolverlo exige una nueva decisión de
   schema e idempotencia.
3. `completed` sólo acredita una respuesta terminal no vacía y sin tools. No
   acredita corrección, aceptación humana, autorización ni éxito del proyecto.
4. `failed` y `ambiguous` no liberan cuota y no autorizan retry. Un nuevo nonce
   requiere otra decisión independiente.
5. Si el observador productivo necesitara enviar, crear sesión, ejecutar tools,
   conservar texto libre o usar una API no soportada, esta autorización termina.

## Evidencia de aceptación

- tarjeta E4-I válida con base y rutas explícitas;
- pruebas focales de reconciliación: 12 casos, incluyendo restart y carrera;
- suite completa: 864 pruebas OK, con 1 skip esperado del host;
- tarjeta válida, enlaces documentales válidos y `git diff --check` OK;
- no existe exportación desde la API raíz ni activación runtime.

El veredicto no autoriza publicación ni operación externa.
