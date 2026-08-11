"""Preflight fail-closed puro para ``epistates/preflight-result/v1``.

Separacion de responsabilidades:

- Las **expectativas** de repositorio, worktree, rama y SHA base provienen de
  ``task_card.target``. ``expected_session_name`` y ``expected_command`` son
  argumentos explicitos del controlador: la tarjeta v1 no tiene identidad de
  sesion, y el adaptador solo declara capacidades.
- Las **observaciones** las inyecta el host (run-context). Esta funcion nunca
  ejecuta subprocess ni consulta el reloj: ``observed_at`` se inyecta y valida.

``evaluate_preflight`` valida primero tarjeta, adaptador e IDs; para
observaciones completas y bien tipadas siempre devuelve un resultado portable
(``ok`` con reasons vacio o ``blocked`` con reasons unicos en orden
determinista). Para observaciones ausentes o mal tipadas lanza ``PreflightError``;
nunca devuelve ``ok``.
"""

import re
from datetime import datetime, timezone
from typing import Any, Mapping, TypedDict

from .adapter import validate_adapter_capabilities
from .audit import canonical_digest
from .contracts import ValidationError, validate_task_card


class PreflightError(ValueError):
    """Una observacion esta ausente, mal tipada o el preflight no puede verificarla."""


_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}")
_SHA_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_UTC_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z")
_PLATFORM_TOKEN_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,31}")

# Orden determinista del catalogo de reasons; cada comprobacion aporta a lo sumo uno.
_REASON_ORDER = (
    "repository_mismatch",
    "worktree_mismatch",
    "cwd_mismatch",
    "branch_drift",
    "sha_drift",
    "dirty",
    "session_mismatch",
    "pane_dead",
    "command_unexpected",
    "platform_unsupported",
)
_REASONS = frozenset(_REASON_ORDER)

_OBSERVED_KEYS = (
    "observed_repository",
    "observed_worktree",
    "observed_cwd",
    "observed_branch",
    "observed_sha",
    "worktree_clean",
    "observed_session_name",
    "pane_alive",
    "observed_command",
    "observed_platform",
)
_OBSERVATION_INPUT_KEYS = frozenset(_OBSERVED_KEYS + ("observed_at",))

_PREFLIGHT_RESULT_FIELDS = frozenset({
    "schema", "task_id", "run_id", "attempt_id", "task_card_digest",
    "adapter_digest", "adapter_id", "observed_at", "outcome", "reasons",
    "observed",
})


def _has_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _require_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe usar minusculas, digitos o guiones")


def _require_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} debe ser sha256:<64 hex>")


def _require_utc(value: Any, field: str, exc: type) -> None:
    if not isinstance(value, str) or not _UTC_PATTERN.fullmatch(value):
        raise exc(f"{field} debe ser RFC3339 UTC terminado en Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise exc(f"{field} debe ser RFC3339 UTC valido") from error
    if parsed.tzinfo != timezone.utc:
        raise exc(f"{field} debe estar en UTC")


def _require_nonempty(value: Any, field: str, exc: type) -> None:
    if not isinstance(value, str) or not value.strip() or _has_surrogate(value):
        raise exc(f"{field} debe ser texto no vacio")


def _require_sha(value: Any, field: str, exc: type) -> None:
    if not isinstance(value, str) or not _SHA_PATTERN.fullmatch(value):
        raise exc(f"{field} debe ser un SHA hex de 40-64 caracteres")


def _require_bool(value: Any, field: str, exc: type) -> None:
    # ``bool`` es subtipo de ``int``: comprobar el tipo exacto antes que nada.
    if not isinstance(value, bool):
        raise exc(f"{field} debe ser booleano")


def _require_token(value: Any, field: str, exc: type) -> None:
    # La plataforma observada es un token canonico lowercase. La pertenencia al
    # manifiesto (adapter.platforms) se comprueba despues, produciendo
    # platform_unsupported. Mayusculas, espacios, slash, control, surrogate o
    # vacio fallan aqui (PreflightError/ValidationError segun la capa).
    if not isinstance(value, str) or not _PLATFORM_TOKEN_PATTERN.fullmatch(value):
        raise exc(f"{field} debe ser un token lowercase canonico")


def _validate_observed_block(observed: Any, exc: type, context: str) -> dict:
    """Valida el bloque de 10 campos (sin ``observed_at``)."""
    if not isinstance(observed, Mapping):
        raise exc(f"{context} debe ser un objeto JSON")
    keys = set(observed.keys())
    missing = set(_OBSERVED_KEYS) - keys
    unknown = keys - set(_OBSERVED_KEYS)
    if missing:
        raise exc(f"{context} campos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise exc(f"{context} campos no soportados: {rendered}")
    _require_nonempty(observed["observed_repository"], "observed_repository", exc)
    _require_nonempty(observed["observed_worktree"], "observed_worktree", exc)
    _require_nonempty(observed["observed_cwd"], "observed_cwd", exc)
    _require_nonempty(observed["observed_branch"], "observed_branch", exc)
    _require_sha(observed["observed_sha"], "observed_sha", exc)
    _require_bool(observed["worktree_clean"], "worktree_clean", exc)
    _require_nonempty(observed["observed_session_name"], "observed_session_name", exc)
    _require_bool(observed["pane_alive"], "pane_alive", exc)
    _require_nonempty(observed["observed_command"], "observed_command", exc)
    _require_token(observed["observed_platform"], "observed_platform", exc)
    return {
        "observed_repository": observed["observed_repository"],
        "observed_worktree": observed["observed_worktree"],
        "observed_cwd": observed["observed_cwd"],
        "observed_branch": observed["observed_branch"],
        "observed_sha": observed["observed_sha"],
        "worktree_clean": observed["worktree_clean"],
        "observed_session_name": observed["observed_session_name"],
        "pane_alive": observed["pane_alive"],
        "observed_command": observed["observed_command"],
        "observed_platform": observed["observed_platform"],
    }


def _validate_observations(observations: Any) -> dict:
    """Valida las 11 observaciones inyectadas por el host (incluye ``observed_at``)."""
    if not isinstance(observations, Mapping):
        raise PreflightError("las observaciones deben ser un objeto JSON")
    keys = set(observations.keys())
    missing = _OBSERVATION_INPUT_KEYS - keys
    unknown = keys - _OBSERVATION_INPUT_KEYS
    if missing:
        raise PreflightError(f"observaciones ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise PreflightError(f"observaciones no soportadas: {rendered}")
    observed_subset = {key: observations[key] for key in _OBSERVED_KEYS}
    block = _validate_observed_block(observed_subset, PreflightError, "observations")
    _require_utc(observations["observed_at"], "observed_at", PreflightError)
    block["observed_at"] = observations["observed_at"]
    return block


def _validate_controller_args(
    expected_run_id: Any, expected_attempt_id: Any,
    expected_session_name: Any, expected_command: Any,
) -> None:
    _require_id(expected_run_id, "expected_run_id")
    _require_id(expected_attempt_id, "expected_attempt_id")
    if not isinstance(expected_session_name, str) or not expected_session_name.strip() or _has_surrogate(expected_session_name):
        raise ValidationError("expected_session_name debe ser texto no vacio")
    if not isinstance(expected_command, str) or not expected_command.strip() or _has_surrogate(expected_command):
        raise ValidationError("expected_command debe ser texto no vacio")


def _compute_reasons(
    target: Mapping[str, Any], adapter: Mapping[str, Any],
    observations: Mapping[str, Any],
    expected_session_name: str, expected_command: str,
) -> list:
    reasons = []
    if observations["observed_repository"] != target["repository"]:
        reasons.append("repository_mismatch")
    if observations["observed_worktree"] != target["worktree"]:
        reasons.append("worktree_mismatch")
    if observations["observed_cwd"] != target["worktree"]:
        reasons.append("cwd_mismatch")
    if observations["observed_branch"] != target["branch"]:
        reasons.append("branch_drift")
    if observations["observed_sha"] != target["base_sha"]:
        reasons.append("sha_drift")
    if observations["worktree_clean"] is not True:
        reasons.append("dirty")
    if observations["observed_session_name"] != expected_session_name:
        reasons.append("session_mismatch")
    if observations["pane_alive"] is not True:
        reasons.append("pane_dead")
    if observations["observed_command"] != expected_command:
        reasons.append("command_unexpected")
    if observations["observed_platform"] not in adapter["platforms"]:
        reasons.append("platform_unsupported")
    return reasons


def evaluate_preflight(
    task_card: Mapping[str, Any],
    adapter: Mapping[str, Any],
    observations: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_attempt_id: str,
    expected_session_name: str,
    expected_command: str,
) -> "PreflightResult":
    """Evalua el preflight de forma pura y fail-closed.

    Valida primero tarjeta, adaptador e IDs; despues las observaciones. Para
    observaciones completas y bien tipadas devuelve siempre un
    ``preflight-result/v1``. Nunca devuelve ``ok`` ante observaciones ausentes o
    mal tipadas: lanza ``PreflightError``.
    """
    validate_task_card(task_card)
    validate_adapter_capabilities(adapter)
    _validate_controller_args(expected_run_id, expected_attempt_id, expected_session_name, expected_command)
    observed = _validate_observations(observations)

    target = task_card["target"]
    reasons = _compute_reasons(target, adapter, observed, expected_session_name, expected_command)
    outcome = "ok" if not reasons else "blocked"
    sanitized = {key: observed[key] for key in _OBSERVED_KEYS}
    return {
        "schema": "epistates/preflight-result/v1",
        "task_id": task_card["task_id"],
        "run_id": expected_run_id,
        "attempt_id": expected_attempt_id,
        "task_card_digest": canonical_digest(task_card),
        "adapter_digest": canonical_digest(adapter),
        "adapter_id": adapter["adapter_id"],
        "observed_at": observed["observed_at"],
        "outcome": outcome,
        "reasons": reasons,
        "observed": sanitized,
    }


class PreflightResult(TypedDict):
    schema: str
    task_id: str
    run_id: str
    attempt_id: str
    task_card_digest: str
    adapter_digest: str
    adapter_id: str
    observed_at: str
    outcome: str
    reasons: list
    observed: dict


def validate_preflight_result(result: Mapping[str, Any]) -> None:
    """Comprueba la coherencia interna de un ``preflight-result/v1`` serializado.

    La validacion estructural no equivale a binding: solo garantiza forma y
    consistencia entre ``outcome`` y ``reasons``.
    """
    if not isinstance(result, Mapping):
        raise ValidationError("el resultado debe ser un objeto JSON")
    missing = _PREFLIGHT_RESULT_FIELDS - result.keys()
    unknown = result.keys() - _PREFLIGHT_RESULT_FIELDS
    if missing:
        raise ValidationError(f"campos requeridos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise ValidationError(f"campos no permitidos: {rendered}")
    if result["schema"] != "epistates/preflight-result/v1":
        raise ValidationError("schema debe ser epistates/preflight-result/v1")
    for field in ("task_id", "run_id", "attempt_id", "adapter_id"):
        _require_id(result[field], field)
    _require_digest(result["task_card_digest"], "task_card_digest")
    _require_digest(result["adapter_digest"], "adapter_digest")
    _require_utc(result["observed_at"], "observed_at", ValidationError)
    outcome = result["outcome"]
    if outcome not in ("ok", "blocked"):
        raise ValidationError("outcome debe ser ok o blocked")
    reasons = result["reasons"]
    if not isinstance(reasons, list):
        raise ValidationError("reasons debe ser una lista")
    seen = set()
    previous_index = -1
    for reason in reasons:
        if not isinstance(reason, str) or reason not in _REASONS:
            raise ValidationError("reasons contiene un valor fuera del catalogo")
        if reason in seen:
            raise ValidationError("reasons contiene un valor duplicado")
        seen.add(reason)
        index = _REASON_ORDER.index(reason)
        if index <= previous_index:
            raise ValidationError("reasons fuera del orden canonico")
        previous_index = index
    if outcome == "ok" and reasons:
        raise ValidationError("outcome ok exige reasons vacio")
    if outcome == "blocked" and not reasons:
        raise ValidationError("outcome blocked exige al menos un reason")
    _validate_observed_block(result["observed"], ValidationError, "observed")


def validate_preflight_binding(
    result: Mapping[str, Any], task_card: Mapping[str, Any],
    adapter: Mapping[str, Any], expected_run_id: str, expected_attempt_id: str,
    expected_session_name: str, expected_command: str,
) -> None:
    """Liga resultado, tarjeta, adaptador y expectativas del controlador.

    La validacion estructural no constituye binding. Aqui se exige correlacion
    exacta de task_id, run/attempt, adapter_id y digests, y despues se recalculan
    los reasons con ``_compute_reasons`` usando ``task_card.target``, el
    adaptador y las expectativas externas (sesion y comando); el ``outcome`` y la
    lista ``reasons`` del resultado deben coincidir exactamente con ese recalculo.
    No se exige que ``observed_session_name`` ni ``observed_command`` sean iguales
    a las expectativas: un ``blocked`` por ``session_mismatch`` o
    ``command_unexpected`` es evidencia valida si coincide con el recalculo.
    """
    validate_preflight_result(result)
    validate_task_card(task_card)
    validate_adapter_capabilities(adapter)
    _validate_controller_args(expected_run_id, expected_attempt_id, expected_session_name, expected_command)
    if result["task_id"] != task_card["task_id"]:
        raise ValidationError("task_id no coincide con la tarjeta")
    if result["run_id"] != expected_run_id:
        raise ValidationError("run_id no coincide con el contexto esperado")
    if result["attempt_id"] != expected_attempt_id:
        raise ValidationError("attempt_id no coincide con el contexto esperado")
    if result["adapter_id"] != adapter["adapter_id"]:
        raise ValidationError("adapter_id no coincide con el adaptador")
    if result["task_card_digest"] != canonical_digest(task_card):
        raise ValidationError("task_card_digest no coincide con la tarjeta")
    if result["adapter_digest"] != canonical_digest(adapter):
        raise ValidationError("adapter_digest no coincide con el adaptador")
    expected_reasons = _compute_reasons(
        task_card["target"], adapter, result["observed"],
        expected_session_name, expected_command,
    )
    expected_outcome = "ok" if not expected_reasons else "blocked"
    if result["outcome"] != expected_outcome:
        raise ValidationError("outcome no coincide con las observaciones")
    if list(result["reasons"]) != expected_reasons:
        raise ValidationError("reasons no coinciden con las observaciones")
