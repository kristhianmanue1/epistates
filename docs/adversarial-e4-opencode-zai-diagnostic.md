# Ronda adversarial — diagnóstico Z.ai/OpenCode E4

Fecha: 2026-08-28

Tarjeta: `e4-opencode-zai-diagnostic`

Decisión: **BLOQUEADO para un nuevo prompt y para wake.**

## Evidencia observada

- Un servidor efímero autenticado y ligado a `127.0.0.1:4096` respondió `200`
  en `GET /global/health`.
- `GET /agent` confirmó `epistates-inspect` configurado para `zai/glm-5.2`.
- `GET /provider` devolvió la forma esperada: el proveedor `zai` está definido,
  pero no está presente en la lista `connected`.
- No se creó sesión, no se envió prompt y no se inició autenticación u OAuth.
- El primer intento de lectura del proveedor agotó 3 s; una segunda lectura con
  límite de 25 s completó. Es un dato de latencia de inicialización, no prueba
  de disponibilidad de Z.ai.

## Ronda adversarial

| Hipótesis | Resultado | Veredicto |
| --- | --- | --- |
| El modelo configurado implica credencial disponible | Rechazado: `zai` está definido pero no conectado. | No enviar otro prompt. |
| Un `204` anterior demuestra que Z.ai recibió la solicitud | Rechazado: el `204` sólo fue aceptación local asíncrona; la desconexión actual explica la ausencia de respuesta. | No hay prueba de inferencia. |
| Conectar el proveedor puede hacerse automáticamente | Rechazado: modificar autenticación, usar OAuth o almacenar una clave excede esta tarjeta. | Requiere autoridad nueva. |
| La demora de `/provider` se puede ignorar | Rechazado: un preflight futuro debe presupuestar esa latencia y fallar cerrado ante timeout. | Riesgo operativo abierto. |
| El diagnóstico habilita wake | Rechazado: no intervienen recibos E3, `WakeGuardStore` ni automatización. | Wake sigue bloqueado. |

## Siguiente decisión requerida

El mantenedor debe autorizar, fuera de Epistates, un método concreto para
conectar Z.ai en OpenCode y su manejo de secreto. Antes de volver a probar un
prompt se requiere un preflight que confirme `zai` en `connected`, sin imprimir
ni versionar credenciales. Esta evidencia no autoriza OAuth, API key,
persistencia de credenciales, wake, commit ni publicación.
