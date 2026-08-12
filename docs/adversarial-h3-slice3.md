# Ronda adversarial — H3 Slice3

**Fecha:** 2026-08-11. **Decisión:** `proceed` para Slice3.
**H3 completo:** abierto; notificación y auditoría post-ejecución siguen fuera
de este corte.

## Alcance revisado

Se auditó la frontera de efecto `TmuxLiteralDispatcher`, la orquestación
`dispatch_literal_opencode_tmux`, el recibo portable
`epistates/dispatch-receipt/v1`, su binding y la integración read-only del CLI.
La revisión no autoriza commit, push, PR ni automatización de señales.

## Hallazgos y correcciones

La primera ronda reprodujo cinco problemas materiales:

- el binding aceptaba un recibo ligado a un mensaje vacío que dispatch prohibía;
- un preflight obsoleto podía ejecutar las dos fases;
- el recibo no identificaba el preflight exacto;
- persistían cálculos capaces de fallar después del efecto;
- un fallo al intentar la fase literal se clasificaba falsamente como certeza de
  no entrega.

La corrección añadió binding por `preflight_result_digest`, política de frescura
inyectada, validación única de mensajes, precálculo total, terminador `--` y las
tres categorías `DispatchError`, `IndeterminateDispatchError` y
`PartialDispatchError`.

La segunda ronda encontró dos evasiones adicionales:

- el recibo podía autoampliar su propia ventana de frescura;
- `--preflight-result` se ignoraba para schemas donde no aplicaba.

El binding ahora recibe `expected_max_preflight_age_seconds` como política
externa, exige igualdad con el recibo y rederiva la frescura con ese valor. El
CLI exige esa política, rechaza opciones inaplicables y lee el archivo de
mensaje con un límite real de `máximo + 1` bytes resistente a crecimiento entre
`stat` y `read`.

## Evidencia independiente

- `git diff --check`: exit 0.
- Suite completa contra este worktree: 318 pruebas correctas; un smoke de tmux
  omitido dentro del sandbox por falta de acceso al socket.
- Regresiones focales de frescura, binding, categorías de fallo, argv cerrado,
  dispatcher de producción, CLI y lectura acotada: 33 pruebas correctas.
- Reproducción externa de política autoampliada: bloqueada con
  `max_preflight_age_seconds no coincide con la política esperada`.
- Opciones `--preflight-result` inaplicables sobre task-card y preflight-result:
  ambas rechazadas por CLI.
- Archivo que reporta tamaño pequeño y devuelve `límite + 1` bytes: bloqueado
  sin lectura ilimitada.
- CLI nominal del recibo con tarjeta, adaptador, preflight, contexto, política
  externa y mensaje: `VALID`.
- Smoke real sobre una sesión tmux desechable: el mensaje
  `-X ; $HOME | literal` fue enviado por el dispatcher sin expansión ni
  interpretación. La sesión de prueba fue eliminada después.

## Riesgos residuales aceptados para v1

- El recibo confirma transporte técnico, no comprensión ni obediencia del
  agente.
- `max_output_bytes` limita la salida después de la captura de
  `subprocess.run`; no es aislamiento de memoria del SO.
- Un resultado indeterminado o parcial exige intervención humana y nunca se
  reintenta automáticamente.
- Los mensajes están limitados a 8192 bytes UTF-8; TAB, CR, NUL, surrogates y
  controles peligrosos se rechazan.
- Sólo se soporta el socket tmux por defecto; `-L` y `-S` quedan fuera de v1.
- La inspección y notificación posteriores a `WAITING_EXTERNAL` pertenecen a
  los siguientes cortes de H3.

## Decisión

`proceed` para H3 Slice3. La implementación liga autoridad, preflight, política
de frescura, mensaje y transporte; separa fallos pre-efecto, indeterminados y
parciales; y no observa ni calcula después de completar Enter. Esta decisión no
cierra H3 ni autoriza operaciones Git o publicación.
