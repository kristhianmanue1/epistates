"""Entrega literal ``opencode-tmux``: la única frontera con efecto de escritura.

Separación de responsabilidades
-------------------------------

- ``host_runner``/``host_observer`` son **read-only**: observan Git y tmux sin
  efectos. Este módulo es la **frontera de dispatch**, separada del runner
  read-only, y contiene la única operación con efecto: ``tmux send-keys``.

Fail-closed antes de cualquier efecto
-------------------------------------

- ``dispatch_literal_opencode_tmux`` valida primero el **binding completo** de un
  ``preflight-result/v1`` con ``outcome == ok`` mediante
  ``validate_preflight_binding``. Si el preflight está bloqueado o mal ligado se
  lanza ``DispatchError`` **sin ninguna llamada** al dispatcher.
- Exige ``current_state == PREPARED``.
- Aplica una política de frescura inyectada (``max_preflight_age_seconds``):
  ``dispatched_at`` no puede preceder a ``observed_at`` ni exceder la edad
  máxima. Todo antes de cualquier efecto.

Precálculo completo antes del primer send
-----------------------------------------

- Antes de llamar al dispatcher se calcula **todo** lo que pueda fallar:
  digests (tarjeta, adaptador, preflight, mensaje), la transición
  ``PREPARED -> DISPATCHED -> WAITING_EXTERNAL`` y el recibo base.
- Después de un Enter exitoso **no queda** canonicalización, validación ni
  transición capaz de lanzar: la función sólo devuelve ``(receipt, state)``.

Dos llamadas cerradas, no shell
-------------------------------

- La entrega usa **exactamente dos** llamadas inyectables:
  1. ``send_literal_text(session, message)`` -> ``tmux send-keys -l -t SESSION
     -- MESSAGE``. ``-l`` = literal (bytes, nunca nombre de tecla); ``--``
     termina opciones para que un mensaje que empiece en ``-`` no se interprete
     como flag.
  2. ``send_enter(session)`` -> ``tmux send-keys -t SESSION Enter``.
- Ambas construyen argv internamente: el caller **nunca** aporta argv. Se
  ejecutan con ``shell=False``, ``stdin=DEVNULL``, executable absoluto, entorno
  mínimo y salida estricta.
- ``TmuxLiteralDispatcher`` aplica la validación completa de sesión y mensaje
  aun cuando se use directamente (no sólo a través de la orquestación).

Mensaje: literal, acotado y fail-closed (validación compartida)
--------------------------------------------------------------

- ``_validate_message`` es la **única** política de mensaje, usada por la
  orquestación, el dispatcher público y el binding del recibo.
- Se rechazan NUL, surrogates y todo control C0 excepto LF (``\\n``), más DEL.
  Se conserva el texto multilínea literal. TAB y CR se rechazan: en un terminal
  TAB dispara completado y CR es ambiguo; sólo LF es necesario para multilínea.
- El mensaje debe tener contenido imprimible, longitud UTF-8 mínima 1 y no
  exceder ``_MESSAGE_MAX_BYTES``.

Sin reintento: tres categorías de fallo
---------------------------------------

- ``DispatchError``: fallo **pre-efecto** (validación, estado, frescura,
  configuración). Nada se intentó enviar.
- ``IndeterminateDispatchError``: la **fase 1** (literal) fue *intentada* y falló
  de forma ambigua (timeout, OSError, exit anómalo). El literal **pudo**
  entregarse: resultado indeterminado. **No reintenta** (duplicaría).
- ``PartialDispatchError``: la fase 1 **confirmó** el literal y la fase 2 (Enter)
  falló de forma indeterminada. **No reintenta**.

Recibo portable ligado al preflight, sin prompt
-----------------------------------------------

- El recibo ``dispatch-receipt/v1`` **no** guarda el mensaje: sólo su digest y
  longitud UTF-8. Se liga al preflight exacto mediante
  ``preflight_result_digest`` y registra ``max_preflight_age_seconds``,
  IDs/digests ligados, sesión, ``dispatched_at`` inyectado, fases confirmadas y
  estado final.
- ``confirms == "technical_transport_only"`` deja explícito que el recibo
  confirma **transporte técnico**, no comprensión del agente ni autoridad.

Tras el éxito completo
----------------------

- Se deriva ``DISPATCHED`` y ``WAITING_EXTERNAL`` mediante la máquina de estados
  pura (precalculada). La función **no observa nada** después de Enter (sin
  ``capture-pane``, sin ``list-panes``, sin polling).
"""

import hashlib
import math
import re
import subprocess
from datetime import datetime, timezone
from os.path import isabs, normpath
from typing import Any, Mapping, Protocol

from .adapter import validate_adapter_capabilities
from .audit import canonical_digest
from .contracts import ValidationError, validate_task_card
from .host_runner import HostObserverError, validate_session_name
from .preflight import validate_preflight_binding
from .state import TransitionError, transition


class DispatchError(ValueError):
    """Fallo pre-efecto: nada se intentó enviar. Categoría pre-efecto."""


class IndeterminateDispatchError(ValueError):
    """Fase 1 intentada y fallada ambiguamente. Resultado indeterminado. NO reintenta."""


class PartialDispatchError(ValueError):
    """Literal confirmado, Enter indeterminado. NO reintenta."""


_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_UTC_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z")

# Límite de bytes UTF-8 del mensaje. v1: una instrucción acotada, no un dump.
_MESSAGE_MAX_BYTES = 8192
# Mensaje vacío prohibido: longitud UTF-8 mínima.
_MESSAGE_MIN_BYTES = 1

_MAX_OUTPUT_CEILING = 16 * 1024 * 1024
_TIMEOUT_FLOOR = 0.0
_TIMEOUT_CEILING = 60.0

# Política de frescura: techo duro para ``max_preflight_age_seconds`` (segundos).
_MAX_PREFLIGHT_AGE_CEILING = 3600

# Entorno mínimo para el dispatcher de tmux. Construido desde cero: sin PATH,
# sin HOME, sin TMUX/TMUX_TMPDIR (evita que el entorno del caller redirija el
# socket) y sin variables Git (irrelevantes para send-keys). tmux usa el socket
# por defecto derivado del UID; v1 no soporta -L/-S.
_DISPATCH_ENV = {"LC_ALL": "C", "LANG": "C"}

_PHASES = ("send_literal", "send_enter")

_DISPATCH_RECEIPT_FIELDS = frozenset({
    "schema", "task_id", "run_id", "attempt_id", "task_card_digest",
    "adapter_digest", "preflight_result_digest", "adapter_id", "session_name",
    "dispatched_at", "max_preflight_age_seconds", "message_digest",
    "message_length_utf8", "phases_confirmed", "final_state", "confirms",
})


def _has_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _require_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe usar minúsculas, dígitos o guiones")


def _require_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe ser sha256:<64 hex>")


def _parse_utc(value: Any, field: str, exc: type) -> datetime:
    """Valida RFC3339 UTC terminado en Z y devuelve el datetime aware."""
    if not isinstance(value, str) or not _UTC_PATTERN.fullmatch(value):
        raise exc(f"{field} debe ser RFC3339 UTC terminado en Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise exc(f"{field} debe ser RFC3339 UTC válido") from error
    if parsed.tzinfo != timezone.utc:
        raise exc(f"{field} debe estar en UTC")
    return parsed


def _require_absolute_executable(path: object, name: str) -> str:
    """Ruta absoluta, normalizada, sin NUL y distinta de raíz (sin probar fs)."""
    if not isinstance(path, str):
        raise DispatchError(f"{name} debe ser una ruta absoluta")
    if "\0" in path:
        raise DispatchError(f"{name} no debe contener NUL")
    segments = path.split("/")
    if path == "/":
        raise DispatchError(f"{name} no debe ser raíz")
    if (not isabs(path) or path.startswith("//")
            or "." in segments or ".." in segments or normpath(path) != path):
        raise DispatchError(f"{name} debe ser absoluta y normalizada")
    return path


def _message_digest(message: str) -> str:
    return "sha256:" + hashlib.sha256(message.encode("utf-8")).hexdigest()


def _message_length(message: str) -> int:
    return len(message.encode("utf-8"))


def _validate_message(message: Any, exc: type = DispatchError) -> str:
    """Política única de mensaje: str, acotada, sin NUL/surrogate/controles.

    Conserva LF (texto multilínea). Rechaza TAB, CR, otros C0 y DEL. Exige
    contenido imprimible y longitud UTF-8 en ``[_MESSAGE_MIN_BYTES,
    _MESSAGE_MAX_BYTES]``. Compartida por orquestación, dispatcher público y
    binding para que las tres capas coincidan exactamente.
    """
    if not isinstance(message, str):
        raise exc("message debe ser texto")
    if "\0" in message:
        raise exc("message no debe contener NUL")
    if _has_surrogate(message):
        raise exc("message no debe contener surrogates")
    for character in message:
        code = ord(character)
        if code < 0x20 and code != 0x0A:
            raise exc("message no debe contener caracteres de control")
        if code == 0x7F:
            raise exc("message no debe contener DEL")
    encoded_len = len(message.encode("utf-8"))
    if encoded_len < _MESSAGE_MIN_BYTES:
        raise exc("message no debe ser vacío")
    if encoded_len > _MESSAGE_MAX_BYTES:
        raise exc("message excede el límite de bytes UTF-8")
    if not any(not ch.isspace() and ch.isprintable() for ch in message):
        raise exc("message debe contener contenido imprimible")
    return message


def _validate_age_policy(max_preflight_age_seconds: Any, exc: type) -> None:
    """Límites de la política de frescura: finito, positivo, acotado."""
    if (not isinstance(max_preflight_age_seconds, (int, float))
            or isinstance(max_preflight_age_seconds, bool)
            or not math.isfinite(max_preflight_age_seconds)
            or not (0 < max_preflight_age_seconds <= _MAX_PREFLIGHT_AGE_CEILING)):
        raise exc(
            f"max_preflight_age_seconds debe ser finito positivo en "
            f"(0, {_MAX_PREFLIGHT_AGE_CEILING:g}]"
        )


def _validate_freshness(
    observed_at: Any, dispatched_at: Any,
    max_preflight_age_seconds: Any, exc: type,
) -> None:
    """Política de frescura: dispatched >= observed y age <= max.

    Usa ``_validate_age_policy`` para los límites y devuelve nada. Todo se
    valida antes de efectos.
    """
    _validate_age_policy(max_preflight_age_seconds, exc)
    observed_dt = _parse_utc(observed_at, "observed_at", exc)
    dispatched_dt = _parse_utc(dispatched_at, "dispatched_at", exc)
    if dispatched_dt < observed_dt:
        raise exc("dispatched_at no puede preceder a observed_at")
    age = (dispatched_dt - observed_dt).total_seconds()
    if age > max_preflight_age_seconds:
        raise exc("dispatched_at excede la edad máxima del preflight")


class LiteralDispatcher(Protocol):
    """Contrato del dispatcher inyectable con efecto de escritura limitado.

    Las operaciones son cerradas: ninguna acepta argv del caller. Una
    implementación de producción usa ``subprocess`` contra ``tmux send-keys``;
    los tests inyectan un fake determinista que registra las llamadas.
    """

    def send_literal_text(self, session_name: str, text: str) -> None: ...
    def send_enter(self, session_name: str) -> None: ...


class TmuxLiteralDispatcher:
    """Dispatcher de producción: dos formas cerradas de ``tmux send-keys``.

    Recibe la ruta absoluta confiable al executable ``tmux`` (no la busca en
    ``PATH``), un ``timeout_seconds`` positivo y un ``max_output_bytes`` acotado.
    Cada operación construye argv internamente y valida sesión + mensaje aun
    cuando el dispatcher se use directamente (no sólo vía la orquestación).
    """

    def __init__(self, tmux_path, timeout_seconds, max_output_bytes):
        self._tmux = _require_absolute_executable(tmux_path, "tmux_path")
        if (not isinstance(timeout_seconds, (int, float))
                or isinstance(timeout_seconds, bool)
                or not math.isfinite(timeout_seconds)
                or not (_TIMEOUT_FLOOR < timeout_seconds <= _TIMEOUT_CEILING)):
            raise DispatchError(
                f"timeout_seconds debe ser un número finito en (0, {_TIMEOUT_CEILING:g}]"
            )
        if (not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool)
                or not (0 < max_output_bytes <= _MAX_OUTPUT_CEILING)):
            raise DispatchError("max_output_bytes debe ser un entero acotado positivo")
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes
        self._env = dict(_DISPATCH_ENV)

    @staticmethod
    def _validate_session(session_name: object) -> str:
        try:
            return validate_session_name(session_name)
        except HostObserverError as error:
            raise DispatchError("session_name debe ser un identificador cerrado") from error

    def _run(self, argv):
        """Ejecuta argv cerrado (shell=False, stdin DEVNULL, env mínimo).

        Una vez invocado ``subprocess.run`` el resultado es **indeterminado**:
        falla cerrado ante timeout, OSError (executable ausente/inaccesible),
        salida sobre el límite, exit no cero, stderr no vacío o stdout
        inesperado, lanzando ``IndeterminateDispatchError``. Los errores no
        incluyen stdout/stderr: sólo la categoría del fallo.
        """
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=None,
                timeout=self._timeout,
                check=False,
                shell=False,
                env=self._env,
            )
        except subprocess.TimeoutExpired as error:
            raise IndeterminateDispatchError("timeout agotado") from error
        except OSError as error:
            raise IndeterminateDispatchError("executable ausente o inaccesible") from error
        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        # Overflow antes de interpretar exit; no inspeccionamos contenido.
        if len(stdout) + len(stderr) > self._max_output:
            raise IndeterminateDispatchError("salida combinada sobre el límite")
        if completed.returncode != 0:
            raise IndeterminateDispatchError("exit no cero")
        if stderr:
            raise IndeterminateDispatchError("stderr no vacío")
        if stdout:
            # send-keys no produce stdout en éxito; cualquier byte es anomalía.
            raise IndeterminateDispatchError("stdout inesperado")

    def send_literal_text(self, session_name, text):
        # Validación completa aun en uso directo: sesión y mensaje.
        session = self._validate_session(session_name)
        _validate_message(text)
        # ``--`` termina opciones: un mensaje que empiece en ``-`` no se parsea
        # como flag. argv list, shell=False.
        argv = [self._tmux, "send-keys", "-l", "-t", session, "--", text]
        self._run(argv)

    def send_enter(self, session_name):
        session = self._validate_session(session_name)
        argv = [self._tmux, "send-keys", "-t", session, "Enter"]
        self._run(argv)


def dispatch_literal_opencode_tmux(
    task_card: Mapping[str, Any],
    adapter: Mapping[str, Any],
    preflight_result: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_attempt_id: str,
    expected_session_name: str,
    expected_command: str,
    message: str,
    dispatched_at: str,
    max_preflight_age_seconds: float,
    current_state: str,
    dispatcher: LiteralDispatcher,
):
    """Entrega literal fail-closed y devuelve ``(receipt, final_state)``.

    Requiere binding completo de un preflight ``ok``, estado ``PREPARED`` y una
    política de frescura inyectada. Precalcula digests, transición y recibo
    antes de enviar; tras un Enter exitoso no queda nada que pueda lanzar.
    """
    # 1. Binding fail-closed del preflight outcome ok (antes de cualquier efecto).
    try:
        validate_preflight_binding(
            preflight_result, task_card, adapter,
            expected_run_id, expected_attempt_id,
            expected_session_name, expected_command,
        )
    except ValidationError as error:
        raise DispatchError("preflight binding inválido") from error
    if preflight_result["outcome"] != "ok":
        raise DispatchError("preflight no es ok; entrega cancelada")
    # 2. Estado PREPARED.
    if current_state != "PREPARED":
        raise DispatchError("dispatch exige estado PREPARED")
    # 3. Validaciones pre-efecto: sesión, mensaje, timestamp, dispatcher, frescura.
    session = _coerce_session(expected_session_name)
    _validate_message(message)
    _parse_utc(dispatched_at, "dispatched_at", DispatchError)
    if dispatcher is None:
        raise DispatchError("dispatcher es requerido")
    _validate_freshness(
        preflight_result["observed_at"], dispatched_at,
        max_preflight_age_seconds, DispatchError,
    )
    # 4. Precálculo de todo lo que pueda fallar, antes del primer send.
    task_card_digest = canonical_digest(task_card)
    adapter_digest = canonical_digest(adapter)
    preflight_result_digest = canonical_digest(preflight_result)
    message_digest = _message_digest(message)
    message_length = _message_length(message)
    try:
        after_dispatch = transition(current_state, "dispatch")
        final_state = transition(after_dispatch, "wait")
    except TransitionError as error:
        raise DispatchError("transición de estado inválida") from error
    if final_state != "WAITING_EXTERNAL":
        raise DispatchError("transición de estado inesperada")
    receipt = {
        "schema": "epistates/dispatch-receipt/v1",
        "task_id": task_card["task_id"],
        "run_id": expected_run_id,
        "attempt_id": expected_attempt_id,
        "task_card_digest": task_card_digest,
        "adapter_digest": adapter_digest,
        "preflight_result_digest": preflight_result_digest,
        "adapter_id": adapter["adapter_id"],
        "session_name": session,
        "dispatched_at": dispatched_at,
        "max_preflight_age_seconds": max_preflight_age_seconds,
        "message_digest": message_digest,
        "message_length_utf8": message_length,
        "phases_confirmed": list(_PHASES),
        "final_state": final_state,
        "confirms": "technical_transport_only",
    }
    # 5. Fase 1: literal. Una vez intentada, un fallo es indeterminado.
    try:
        dispatcher.send_literal_text(session, message)
    except DispatchError:
        # Validación pre-subprocess del dispatcher (nada enviado). La
        # orquestación ya validó, así que esto es defensivo.
        raise
    except Exception as error:
        raise IndeterminateDispatchError(
            "fase 1 intentada: resultado indeterminado; NO reintentar"
        ) from error
    # 6. Fase 2: Enter. Literal confirmado; fallo aquí es parcial indeterminado.
    try:
        dispatcher.send_enter(session)
    except Exception as error:
        raise PartialDispatchError(
            "literal confirmado, Enter indeterminado; NO reintentar"
        ) from error
    # 7. Éxito completo: todo estaba precalculado. Sólo devolver.
    return receipt, final_state


def _coerce_session(value: Any) -> str:
    try:
        return validate_session_name(value)
    except HostObserverError as error:
        raise DispatchError("session_name debe ser un identificador cerrado") from error


def validate_dispatch_receipt(receipt: Mapping[str, Any]) -> None:
    """Validación estructural de ``dispatch-receipt/v1`` (sin refs externas)."""
    if not isinstance(receipt, Mapping):
        raise ValidationError("el recibo debe ser un objeto JSON")
    missing = _DISPATCH_RECEIPT_FIELDS - receipt.keys()
    unknown = receipt.keys() - _DISPATCH_RECEIPT_FIELDS
    if missing:
        raise ValidationError(f"campos requeridos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise ValidationError(f"campos no permitidos: {rendered}")
    if receipt["schema"] != "epistates/dispatch-receipt/v1":
        raise ValidationError("schema debe ser epistates/dispatch-receipt/v1")
    for field in ("task_id", "run_id", "attempt_id", "adapter_id"):
        _require_id(receipt[field], field)
    _require_digest(receipt["task_card_digest"], "task_card_digest")
    _require_digest(receipt["adapter_digest"], "adapter_digest")
    _require_digest(receipt["preflight_result_digest"], "preflight_result_digest")
    _require_digest(receipt["message_digest"], "message_digest")
    try:
        validate_session_name(receipt["session_name"])
    except HostObserverError as error:
        raise ValidationError("session_name debe ser un identificador cerrado") from error
    _parse_utc(receipt["dispatched_at"], "dispatched_at", ValidationError)
    age_policy = receipt["max_preflight_age_seconds"]
    _validate_age_policy(age_policy, ValidationError)
    length = receipt["message_length_utf8"]
    if (not isinstance(length, int) or isinstance(length, bool)
            or length < _MESSAGE_MIN_BYTES or length > _MESSAGE_MAX_BYTES):
        raise ValidationError(
            "message_length_utf8 debe ser un entero en [1, _MESSAGE_MAX_BYTES]"
        )
    phases = receipt["phases_confirmed"]
    if not isinstance(phases, list) or tuple(phases) != _PHASES:
        raise ValidationError("phases_confirmed debe ser [send_literal, send_enter]")
    if receipt["final_state"] != "WAITING_EXTERNAL":
        raise ValidationError("final_state debe ser WAITING_EXTERNAL")
    if receipt["confirms"] != "technical_transport_only":
        raise ValidationError("confirms debe ser technical_transport_only")


def validate_dispatch_receipt_binding(
    receipt: Mapping[str, Any],
    task_card: Mapping[str, Any],
    adapter: Mapping[str, Any],
    preflight_result: Mapping[str, Any],
    expected_run_id: str,
    expected_attempt_id: str,
    expected_session_name: str,
    expected_command: str,
    expected_max_preflight_age_seconds: float,
    message: str,
) -> None:
    """Liga recibo, tarjeta, adaptador, **preflight exacto**, contexto y mensaje.

    Recibe y valida el preflight completo (``outcome == ok``, IDs, sesión y
    ``expected_command`` mediante ``validate_preflight_binding``) y exige que
    ``preflight_result_digest`` coincida con el preflight ligado.

    La política de frescura es **externa** (``expected_max_preflight_age_seconds``):
    se valida con los mismos límites, se exige **igualdad exacta** con el valor
    del recibo (para impedir auto-ampliación) y se re_deriva la frescura con la
    política externa. Nunca se confía sólo en el recibo.

    Valida el mensaje con la misma política (``_validate_message``) que la
    orquestación y el dispatcher.
    """
    validate_dispatch_receipt(receipt)
    validate_task_card(task_card)
    validate_adapter_capabilities(adapter)
    # Preflight exacto: binding completo con outcome implícito en el recálculo.
    validate_preflight_binding(
        preflight_result, task_card, adapter,
        expected_run_id, expected_attempt_id,
        expected_session_name, expected_command,
    )
    if preflight_result["outcome"] != "ok":
        raise ValidationError("preflight no es ok")
    # Política externa del controlador: límites + igualdad exacta con el recibo.
    _validate_age_policy(expected_max_preflight_age_seconds, ValidationError)
    if receipt["max_preflight_age_seconds"] != expected_max_preflight_age_seconds:
        raise ValidationError(
            "max_preflight_age_seconds no coincide con la política esperada"
        )
    if receipt["task_id"] != task_card["task_id"]:
        raise ValidationError("task_id no coincide con la tarjeta")
    if receipt["run_id"] != expected_run_id:
        raise ValidationError("run_id no coincide con el contexto esperado")
    if receipt["attempt_id"] != expected_attempt_id:
        raise ValidationError("attempt_id no coincide con el contexto esperado")
    if receipt["adapter_id"] != adapter["adapter_id"]:
        raise ValidationError("adapter_id no coincide con el adaptador")
    if receipt["task_card_digest"] != canonical_digest(task_card):
        raise ValidationError("task_card_digest no coincide con la tarjeta")
    if receipt["adapter_digest"] != canonical_digest(adapter):
        raise ValidationError("adapter_digest no coincide con el adaptador")
    if receipt["preflight_result_digest"] != canonical_digest(preflight_result):
        raise ValidationError("preflight_result_digest no coincide con el preflight")
    if receipt["session_name"] != expected_session_name:
        raise ValidationError("session_name no coincide con el esperado")
    # Misma política de mensaje que la orquestación y el dispatcher.
    _validate_message(message, ValidationError)
    if receipt["message_digest"] != _message_digest(message):
        raise ValidationError("message_digest no coincide con el mensaje")
    if receipt["message_length_utf8"] != _message_length(message):
        raise ValidationError("message_length_utf8 no coincide con el mensaje")
    # Re_deriva la frescura con la política EXTERNA, no la del recibo.
    _validate_freshness(
        preflight_result["observed_at"], receipt["dispatched_at"],
        expected_max_preflight_age_seconds, ValidationError,
    )
