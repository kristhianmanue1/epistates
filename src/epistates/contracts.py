"""Validación read-only de contratos; nunca ejecuta comandos de una tarjeta."""

import re
from os.path import isabs, normpath
from typing import Any, Mapping


class ValidationError(ValueError):
    """Un artefacto no satisface su contrato declarado."""


_TOP_LEVEL = {
    "schema", "task_id", "objective", "target", "role", "allowed_paths",
    "authority", "allowed_actions", "forbidden_operations", "inputs", "checks",
    "evidence", "delivery", "stop_condition", "new_decision_required_for",
}
_PROTECTED_OPERATIONS = {"commit", "push", "open_pr", "merge", "release"}
_ACTIONS = {"read", "edit", "run_checks"}
_OPERATIONS = _PROTECTED_OPERATIONS | {
    "install_dependencies", "change_scope", "git_reset", "create_branch",
    "delete_branch", "create_worktree", "remove_worktree",
}
_ROLES = {"developer", "qa", "documenter"}
_CHECK_IDS = {"git_status", "diff_check", "unit_tests"}
_EVIDENCE = {"worktree_status", "diff_check", "check_results"}


def _require_string(value: Any, field: str) -> None:
    if (not isinstance(value, str) or not value.strip()
            or any(0xD800 <= ord(character) <= 0xDFFF for character in value)):
        raise ValidationError(f"{field} debe ser texto no vacío")


def _require_string_list(value: Any, field: str, *, nonempty: bool = True) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValidationError(f"{field} debe ser una lista no vacía")
    for item in value:
        _require_string(item, field)


def validate_task_card(card: Mapping[str, Any]) -> None:
    """Comprueba forma y garantías mínimas de ``epistates/task-card/v1``."""
    if not isinstance(card, Mapping):
        raise ValidationError("la tarjeta debe ser un objeto JSON")
    missing = _TOP_LEVEL - card.keys()
    unknown = card.keys() - _TOP_LEVEL
    if missing:
        raise ValidationError(f"campos requeridos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise ValidationError(f"campos no permitidos: {rendered}")
    if card["schema"] != "epistates/task-card/v1":
        raise ValidationError("schema debe ser epistates/task-card/v1")
    if not isinstance(card["task_id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", card["task_id"]):
        raise ValidationError("task_id debe usar minúsculas, dígitos o guiones (3-64 caracteres)")
    _require_string(card["objective"], "objective")
    target = card["target"]
    if not isinstance(target, Mapping) or set(target) != {"repository", "base_sha", "branch", "worktree"}:
        raise ValidationError("target debe contener sólo repository, base_sha, branch y worktree")
    for field in target:
        _require_string(target[field], f"target.{field}")
    if not re.fullmatch(r"[0-9a-f]{40,64}", target["base_sha"]):
        raise ValidationError("target.base_sha debe ser un SHA hexadecimal de 40 a 64 caracteres")
    worktree = target["worktree"]
    segments = worktree.split("/")
    if (not isabs(worktree) or worktree == "/" or worktree.startswith("//")
            or "." in segments or ".." in segments or normpath(worktree) != worktree):
        raise ValidationError("target.worktree debe ser una ruta absoluta, normalizada y distinta de raíz")
    if not isinstance(card["role"], str) or card["role"] not in _ROLES:
        raise ValidationError("role no está soportado")
    authority = card["authority"]
    if not isinstance(authority, Mapping) or set(authority) != {"grant_id", "granted_by", "granted_actions", "protected_operations_authorized"}:
        raise ValidationError("authority debe declarar grant_id, granted_by, granted_actions y protected_operations_authorized")
    if not isinstance(authority["grant_id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", authority["grant_id"]):
        raise ValidationError("authority.grant_id debe usar minúsculas, dígitos o guiones")
    if authority["granted_by"] != "maintainer":
        raise ValidationError("authority.granted_by debe ser maintainer")
    if not isinstance(authority["granted_actions"], list) or not authority["granted_actions"] or any(not isinstance(action, str) or action not in _ACTIONS for action in authority["granted_actions"]):
        raise ValidationError("authority.granted_actions contiene una acción no soportada")
    if not isinstance(authority["protected_operations_authorized"], list) or authority["protected_operations_authorized"]:
        raise ValidationError("v1 no permite operaciones protegidas autorizadas")
    _require_string_list(card["allowed_paths"], "allowed_paths")
    if any(path.startswith("/") or ".." in path.split("/") for path in card["allowed_paths"]):
        raise ValidationError("allowed_paths debe permanecer dentro del worktree")
    if not isinstance(card["allowed_actions"], list) or any(not isinstance(action, str) or action not in _ACTIONS for action in card["allowed_actions"]):
        raise ValidationError("allowed_actions contiene una acción no soportada")
    if not card["allowed_actions"] or not set(card["allowed_actions"]).issubset(set(authority["granted_actions"])):
        raise ValidationError("allowed_actions excede authority.granted_actions")
    forbidden = card["forbidden_operations"]
    if not isinstance(forbidden, list) or not forbidden:
        raise ValidationError("forbidden_operations debe declarar prohibiciones explícitas")
    if any(not isinstance(operation, str) or operation not in _OPERATIONS for operation in forbidden):
        raise ValidationError("forbidden_operations contiene una operación no soportada")
    omitted = _PROTECTED_OPERATIONS - set(forbidden)
    if omitted:
        raise ValidationError(f"operaciones protegidas sin prohibición explícita: {', '.join(sorted(omitted))}")
    _require_string_list(card["inputs"], "inputs")
    if any(path.startswith("/") or ".." in path.split("/") for path in card["inputs"]):
        raise ValidationError("inputs debe permanecer dentro del worktree")
    checks = card["checks"]
    if not isinstance(checks, list) or not checks:
        raise ValidationError("checks debe ser una lista no vacía")
    for check in checks:
        if not isinstance(check, Mapping) or set(check) != {"check_id", "expected"}:
            raise ValidationError("cada check debe contener sólo check_id y expected")
        if not isinstance(check["check_id"], str) or check["check_id"] not in _CHECK_IDS:
            raise ValidationError("checks[].check_id no está en el catálogo confiable")
        _require_string(check["expected"], "checks[].expected")
    evidence = card["evidence"]
    if not isinstance(evidence, Mapping) or set(evidence) != {"report_format", "required"}:
        raise ValidationError("evidence debe contener sólo report_format y required")
    if evidence["report_format"] != "rag/v1":
        raise ValidationError("evidence.report_format debe ser rag/v1")
    if not isinstance(evidence["required"], list) or not evidence["required"] or any(not isinstance(item, str) or item not in _EVIDENCE for item in evidence["required"]):
        raise ValidationError("evidence.required contiene evidencia no soportada")
    for field in ("delivery", "stop_condition"):
        _require_string(card[field], field)
    _require_string_list(card["new_decision_required_for"], "new_decision_required_for")
