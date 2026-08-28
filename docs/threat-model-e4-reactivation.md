# Threat model — E4 reactivación soportada

## Activos y fronteras

| Activo | Riesgo a evitar |
| --- | --- |
| Policy persistente | Que texto, señal o configuración efímera habilite wake. |
| Kill switch persistente | Que un retry, restart o carrera lo ignore. |
| Ledger nonce/cuota | Doble wake, replay y abuso de tasa. |
| Binding de destino | Wake de tarea o sesión equivocada. |
| Puerto público | Confused deputy hacia endpoint privado o falso. |
| Resultado | Convertir `queued` en ejecución o permiso posterior. |

## Amenazas y mitigaciones requeridas

| Amenaza | Mitigación antes de cualquier llamada |
| --- | --- |
| Señal E3 falsificada o replay | Recibo atómico ligado al dispatch; no concede policy. |
| Dos controladores / retry tras timeout | Reserva durable y atómica; resultado ambiguo no se reintenta. |
| Kill switch durante la carrera | Lectura antes de reservar y relectura antes del puerto; ambas fail-closed. |
| Flood por destino o global | Token bucket durable global y por identidad de destino. |
| Reloj regresivo o TTL malformado | UTC estricto; reloj inválido o regresivo bloquea. |
| Endpoint suplantado | Registro estático de proveedor, versión y capabilities aprobado; sin descubrimiento dinámico. |
| Credencial excesiva | Mínimo alcance, fuera de artefactos y logs; una tarea futura debe definirla. |
| Resultado de red ambiguo | Retener reserva; no inferir éxito ni repetir automáticamente. |
| Wake usado para mutar o aceptar | API sólo expresa wake; pasos posteriores conservan su propia autorización. |

## Suposiciones y bloqueo

Un proceso local o proveedor comprometido puede mentir; resultados del puerto son datos, no atestaciones. No existe aún identidad criptográfica de agente ni API de proveedor autorizada. No se implementa E4 sin proveedor público verificable, almacenamiento durable de los tres controles, modelo de identidad de destino, pruebas de crash/restart y revisión adversarial fresca del código final.
