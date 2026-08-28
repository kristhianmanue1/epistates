# Ronda adversarial — respuesta terminal OpenCode E4

Fecha: 2026-08-28

Tarjeta: `e4-opencode-terminal-response`

Decisión: **BLOQUEADO para nuevos prompts y para wake automático.**

## Evidencia observada

- Dos intentos de esta tarjeta pasaron `health`, agente y proveedor conectado.
- Cada intento creó una sesión efímera y envió exactamente un prompt fijo;
  ambos `prompt_async` devolvieron `204`.
- OpenCode creó un marcador `assistant` sin partes, texto, error terminal ni
  tiempo de finalización.
- `GET /session/status` expuso estado `retry`. En el segundo intento se observó
  el contador interno `attempt=5` y el mensaje saneado indicó saldo insuficiente
  o ausencia de paquete de recursos.
- No se observaron partes `tool` ni cambios del árbol durante los intentos. Las
  sesiones se eliminaron y los servidores loopback se detuvieron.
- El tercer intento permitido no se ejecutó porque la causa ya era concluyente
  y repetirla sólo consumiría cuota local y ruido operacional.

## Diagnóstico

La cadena local funciona hasta el acuse asíncrono de OpenCode y la credencial de
Z.ai aparece conectada. El bloqueo actual está después del encolado: la cuenta o
proyecto Z.ai no dispone de saldo o paquete de recursos utilizable para
`glm-5.2`. `connected` prueba que OpenCode reconoce una autenticación; no prueba
saldo, cuota, autorización del modelo ni capacidad de producir una respuesta.

Los ensayos también corrigieron dos supuestos inválidos del verificador:

1. La existencia de un mensaje `assistant` no implica respuesta; puede ser un
   marcador vacío mientras el proveedor trabaja o reintenta.
2. `/session/status` puede devolver un objeto durante actividad y un arreglo
   vacío cuando ya no hay sesiones activas. El consumidor debe validar ambas
   formas o fallar cerrado.

## Ronda adversarial

| Hipótesis | Resultado | Veredicto |
| --- | --- | --- |
| `204` significa wake entregado | Rechazado: sólo acredita aceptación local asíncrona. | No usarlo como evidencia de entrega. |
| `zai` conectado significa inferencia disponible | Rechazado por el error de saldo/paquete. | Añadir preflight de capacidad o reconciliación posterior. |
| Repetir el prompt puede resolverlo | Rechazado: OpenCode ya reintentó cinco veces. | Detener hasta corregir la cuenta externa. |
| El modelo pudo actuar pese al fallo | No hubo partes `tool`, la política efectiva fue deny y el árbol no cambió. | Sin efecto observado. |
| Consumir una reserva al recibir `204` es seguro | Rechazado: puede perder una señal cuando el proveedor falla después del acuse. | Falta estado durable de entrega. |
| Este diagnóstico autoriza wake automático | Rechazado: no intervino E3, el guard ni un contrato de entrega. | Wake sigue fuera de alcance. |

## Requisitos antes de continuar

1. El mantenedor debe habilitar saldo o un paquete de recursos Z.ai fuera del
   repositorio, sin copiar credenciales a Epistates.
2. Un preflight posterior debe obtener una respuesta terminal con texto no
   vacío y cero herramientas.
3. Antes de cualquier wake automático, E4 necesita separar durablemente
   `reserved`, `submitted`, `completed` y `failed`; `204` sólo puede producir
   `submitted`.
4. La reconciliación debe observar el resultado terminal y aplicar una política
   de fallo/reintento acotada sin reutilizar nonce ni conceder nuevo permiso.

Este documento sustituye, para el estado operativo actual, las conclusiones
provisionales de los preflights anteriores. Conserva aquellos artefactos como
historial; no los convierte en autorización.
