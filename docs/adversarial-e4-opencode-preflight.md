# Ronda adversarial — preflight OpenCode E4

Fecha: 2026-08-28

Tarjeta: `e4-opencode-preflight`

Decisión: **BLOQUEADO para `prompt_async` y wake real.**

## Evidencia observada

- Un servidor efímero `opencode serve` en `127.0.0.1:4096`, protegido con una
  contraseña aleatoria no persistida, respondió `200` a `GET /global/health`.
- `GET /agent` registró exactamente un agente `epistates-inspect` con el modelo
  `zai/glm-5.2`.
- No se creó sesión ni se llamó `POST /session/:id/prompt_async`; por tanto no
  hubo wake ni inferencia.
- La regla específica del agente resuelta incluye `* -> deny` y
  `external_directory -> deny`, pero OpenCode conserva después una excepción
  global `external_directory -> allow` para su directorio de resultados.

## Ataques y veredicto

| Hipótesis adversarial | Resultado | Efecto |
| --- | --- | --- |
| Un evento local concede permiso operativo | Rechazado: el preflight sólo consultó `health` y `agent`; no hay ruta de evento a acción. | No procede wake. |
| El modelo puede ejecutar herramientas o leer el repositorio | La regla general deniega herramientas, pero la excepción heredada de `external_directory` impide probar un aislamiento absoluto con la configuración actual. | Bloquea activación. |
| Una credencial queda reutilizable | Rechazado: se generó por proceso, nunca se escribió y el servidor se detuvo al finalizar cada consulta. | Sin secreto persistente. |
| El servicio queda expuesto en red | Rechazado: se ligó sólo a `127.0.0.1` y se detuvo. | Sin listener persistente. |
| Health equivale a permiso para despertar | Rechazado: salud y registro prueban disponibilidad/configuración, no autorización ni acción. | E4 continúa en diseño/preflight. |

## Condición para reabrir

Antes de autorizar una prueba de `prompt_async`, se requiere una decisión nueva
del mantenedor que acepte explícitamente la excepción heredada o un mecanismo
documentado que la elimine de la configuración efectiva. También siguen siendo
obligatorios el guard persistente, rate limit, kill switch, contrato de mensaje
fijo y una ronda adversarial fresca del flujo completo.
