"""Canonical schema catalog: closed, immutable, single-source, fail-closed.

This module is the ONLY normative accessor for the seven Epistates JSON Schemas.
The schemas live as package data under ``epistates/data/schemas/`` and are read
via ``importlib.resources`` so the installed wheel exposes them without a source
checkout. There is no second normative copy: the repository ``schemas/``
directory was removed when the canonical source moved into the package.

Frontera que este modulo respeta (y representa machine-readable):

```text
schema-valido != semanticamente-valido != ligado != ejecutable
ejemplo != instruccion != grant
```

Cada schema se identifica como ``validation_scope: structural_only``: el JSON
Schema solo expresa un subconjunto de la forma. El validador Python nombrado en
cada descriptor es **normativo** para la semantica. ``$id`` es un identificador
opaco; **nunca** es una URL a descargar o abrir en runtime, y este modulo no
realiza ninguna operacion de red.

Seguridad (todo fail-closed):

- el ``schema_id`` **nunca** se usa como path: se busca en un catalogo cerrado
  por igualdad exacta. ``../``, path absoluto, ``%2e%2e``, Unicode/confusables y
  caracteres de control (Cc) no matchean ninguna entrada y se rechazan;
- los recursos se leen con ``importlib.resources`` (paquete instalado), no desde
  filesystem/cwd del host;
- cada lectura recomputa ``sha256`` y lo compara con el digest declarado
  (constante congelada): divergencia = fallo;
- el contenido debe ser UTF-8 valido, JSON valido, sin claves duplicadas y
  ASCII puro; cualquier otra condicion falla cerrado;
- sin subprocess, sin socket, sin reloj, sin Git, sin tmux, sin red.

Autoridad: mostrar o validar un schema **nunca** concede autoridad ni
ejecutabilidad. Todo descriptor fija ``library_authenticates_authority: false`` y
``authorized_to_execute: false``.
"""

import hashlib
import json
from importlib.resources import files
from typing import Any, Dict, List, Mapping, Tuple

from .contracts import ValidationError


class SchemaError(ValueError):
    """Acceso a schema fallido (id desconocido, recurso ausente, digest divergente, \
    contenido invalido)."""


# ---------------------------------------------------------------------------
# Catalogo cerrado e inmutable.
# ---------------------------------------------------------------------------
#
# ``_SCHEMA_RESOURCES`` mapea cada id estable al nombre del recurso empaquetado.
# El id **no** es una ruta: es una clave opaca. El nombre de recurso viene del
# catalogo cerrado, nunca del caller.

_SCHEMA_RESOURCES: Dict[str, str] = {
    "epistates/task-card/v1": "task-card-v1.schema.json",
    "epistates/adapter-capabilities/v1": "adapter-capabilities-v1.schema.json",
    "epistates/audit-result/v1": "audit-result-v1.schema.json",
    "epistates/preflight-result/v1": "preflight-result-v1.schema.json",
    "epistates/dispatch-receipt/v1": "dispatch-receipt-v1.schema.json",
    "epistates/human-notice/v1": "human-notice-v1.schema.json",
    "epistates/review-evidence/v1": "review-evidence-v1.schema.json",
}

# Digests esperados (constantes congeladas) calculados sobre los bytes exactos
# del recurso canonico. Una divergencia detectada en runtime = recurso corrupto
# o manipulado => fail-closed.
_SCHEMA_DIGESTS: Dict[str, str] = {
    "epistates/task-card/v1":
        "a9bbea1f3711802f4680dbf7fa89738cb506fa28e2ba965b723aa1817b39c7ee",
    "epistates/adapter-capabilities/v1":
        "d4073d704a543300ad4b827aee8024d885d12e3caafe893af397e95e03516ee9",
    "epistates/audit-result/v1":
        "9cbab7375ec51dcd6f9ba8a8f685a8d934a36535ac8f3aaa45b95db78e6d5e96",
    "epistates/preflight-result/v1":
        "770c82fefdd352d137b840d17bdc64379cb7c3253568c149e83c90152fdf1190",
    "epistates/dispatch-receipt/v1":
        "398f2ebf716cd163862c3e15ae27a21eecd1b7dec886a86edfb045efe5d390cb",
    "epistates/human-notice/v1":
        "6f86315494ca744b8ccc0f33f2e12ae8c944eb716fa1309d4cbd05814b70c7b7",
    "epistates/review-evidence/v1":
        "1074a21a36a9d4e9f82997439e5215177e248c7036254ce4f81e25c38d7b05ff",
}

# ``$id`` declarado dentro de cada schema. Es un identificador opaco; este modulo
# **nunca** lo abre, resuelve o descarga.
_SCHEMA_JSON_IDS: Dict[str, str] = {
    "epistates/task-card/v1":
        "https://epistates.dev/schemas/task-card-v1.schema.json",
    "epistates/adapter-capabilities/v1":
        "https://epistates.dev/schemas/adapter-capabilities-v1.schema.json",
    "epistates/audit-result/v1":
        "https://epistates.dev/schemas/audit-result-v1.schema.json",
    "epistates/preflight-result/v1":
        "https://epistates.dev/schemas/preflight-result-v1.schema.json",
    "epistates/dispatch-receipt/v1":
        "https://epistates.dev/schemas/dispatch-receipt-v1.schema.json",
    "epistates/human-notice/v1":
        "https://epistates.dev/schemas/human-notice-v1.schema.json",
    "epistates/review-evidence/v1":
        "https://epistates.dev/schemas/review-evidence-v1.schema.json",
}

# Validador Python normativo (metadata). El JSON Schema es structural_only; el
# validador nombrado es normativo para la semantica completa del contrato.
_SCHEMA_VALIDATORS: Dict[str, Tuple[str, str]] = {
    "epistates/task-card/v1":
        ("validate_task_card", "epistates.contracts"),
    "epistates/adapter-capabilities/v1":
        ("validate_adapter_capabilities", "epistates.adapter"),
    "epistates/audit-result/v1":
        ("validate_audit_result", "epistates.audit"),
    "epistates/preflight-result/v1":
        ("validate_preflight_result", "epistates.preflight"),
    "epistates/dispatch-receipt/v1":
        ("validate_dispatch_receipt", "epistates.dispatch"),
    "epistates/human-notice/v1":
        ("validate_human_notice", "epistates.human_notice"),
    "epistates/review-evidence/v1":
        ("validate_review_evidence", "epistates.review"),
}

# Bindings externos requeridos por el CLI ``validate`` para cada schema. Sincronizado
# con ``epistates.__main__._APPLICABLE``; un test de paridad lo garantiza.
_SCHEMA_REQUIRED_BINDINGS: Dict[str, Tuple[str, ...]] = {
    "epistates/task-card/v1": (),
    "epistates/adapter-capabilities/v1": (),
    "epistates/audit-result/v1":
        ("task_card", "run_id", "attempt_id"),
    "epistates/preflight-result/v1":
        ("task_card", "adapter_capabilities", "run_id", "attempt_id",
         "expected_session_name", "expected_command"),
    "epistates/dispatch-receipt/v1":
        ("task_card", "adapter_capabilities", "preflight_result", "run_id",
         "attempt_id", "expected_session_name", "expected_command",
         "max_preflight_age_seconds", "message_file"),
    "epistates/human-notice/v1":
        ("task_card", "adapter_capabilities", "dispatch_receipt", "run_id",
         "attempt_id", "expected_session_name", "max_dispatch_age_seconds"),
    "epistates/review-evidence/v1":
        ("task_card", "adapter_capabilities", "preflight_result",
         "dispatch_receipt", "human_notice", "run_id", "attempt_id",
         "expected_session_name", "expected_command", "message_file",
         "max_preflight_age_seconds", "max_dispatch_age_seconds",
         "max_notice_age_seconds"),
}

# binding_behavior por schema (coherente con discovery.py):
# - task-card / adapter: no participan en binding estructural del CLI.
# - los demas: su binding es correlation_only.
_SCHEMA_BINDING_BEHAVIOR: Dict[str, str] = {
    "epistates/task-card/v1": "none",
    "epistates/adapter-capabilities/v1": "none",
    "epistates/audit-result/v1": "correlation_only",
    "epistates/preflight-result/v1": "correlation_only",
    "epistates/dispatch-receipt/v1": "correlation_only",
    "epistates/human-notice/v1": "correlation_only",
    "epistates/review-evidence/v1": "correlation_only",
}

_VALIDATION_SCOPE = "structural_only"
_RESOURCE_PACKAGE = "epistates"
_RESOURCE_SUBPATH = ("data", "schemas")


# ---------------------------------------------------------------------------
# Helpers internos.
# ---------------------------------------------------------------------------


def _reject_control_chars(value: str) -> None:
    """Defensa en profundidad: un id con Cc (C0+DEL+C1) nunca es catalogado."""
    for ch in value:
        code = ord(ch)
        if code <= 0x1F or 0x7F <= code <= 0x9F:
            raise SchemaError(f"schema_id contiene un carácter de control: {code:#x}")


def _require_known_id(schema_id: Any) -> str:
    if not isinstance(schema_id, str):
        raise SchemaError("schema_id debe ser texto")
    if not schema_id:
        raise SchemaError("schema_id vacío")
    _reject_control_chars(schema_id)
    # Path traversal / absolutos / percent-encoded no matchean ninguna clave: el
    # catalogo se consulta por igualdad exacta de strings. Lo explicitamos con
    # un rechazo claro para que el fallo sea legible.
    if schema_id != schema_id.strip():
        raise SchemaError("schema_id no debe tener espacios en los extremos")
    if schema_id not in _SCHEMA_RESOURCES:
        raise SchemaError(f"schema_id desconocido: {schema_id!r}")
    return schema_id


def _reject_duplicate_keys(pairs):
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"clave JSON duplicada en schema: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise SchemaError(f"constante JSON no soportada en schema: {value}")


def _resource_path(resource_name: str):
    """Resuelve el recurso empaquetado via importlib.resources (sin cwd del host)."""
    return files(_RESOURCE_PACKAGE).joinpath(*_RESOURCE_SUBPATH, resource_name)


def _read_and_verify(schema_id: str) -> bytes:
    """Lee bytes via importlib.resources, recomputa sha256 y verifica fail-closed."""
    resource_name = _SCHEMA_RESOURCES[schema_id]
    expected = _SCHEMA_DIGESTS[schema_id]
    try:
        path = _resource_path(resource_name)
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise SchemaError(
            f"recurso de schema ausente en el paquete: {resource_name}"
        ) from exc
    except OSError as exc:
        raise SchemaError(
            f"no se pudo leer el recurso de schema: {resource_name}"
        ) from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise SchemaError(
            f"digest divergente para {schema_id}: esperado sha256:{expected} "
            f"obtenido sha256:{actual}"
        )
    return raw


# ---------------------------------------------------------------------------
# Accessors publicos (todos devuelven copias/bytes frescos).
# ---------------------------------------------------------------------------


def schema_ids() -> List[str]:
    """IDs estables y ordenados del catalogo cerrado (copia fresca)."""
    return sorted(_SCHEMA_RESOURCES.keys())


def schema_count() -> int:
    """Numero de schemas catalogados (constante: siete)."""
    return len(_SCHEMA_RESOURCES)


def read_schema_bytes(schema_id: str) -> bytes:
    """Bytes frescos del schema (verifica digest). Mutarlos no contamina."""
    schema_id = _require_known_id(schema_id)
    return _read_and_verify(schema_id)


def read_schema_text(schema_id: str) -> str:
    """Texto UTF-8 estricto del schema (verifica digest)."""
    raw = read_schema_bytes(schema_id)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Invariante: los schemas canonico son ASCII puro. Si esto salta, el
        # recurso fue alterado.
        raise SchemaError(f"schema no es UTF-8 válido: {schema_id}") from exc


def read_schema_document(schema_id: str) -> Dict[str, Any]:
    """Documento JSON parseado (sin claves duplicadas, sin NaN/Infinity)."""
    text = read_schema_text(schema_id)
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise SchemaError(f"schema no es JSON válido: {schema_id}: {exc}") from exc
    except SchemaError:
        raise
    except ValueError as exc:
        raise SchemaError(f"schema JSON inválido: {schema_id}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SchemaError(f"schema no es un objeto JSON: {schema_id}")
    return parsed


def schema_descriptor(schema_id: str) -> Dict[str, Any]:
    """Descriptor fresco y completo de un schema (copia nueva cada llamada)."""
    schema_id = _require_known_id(schema_id)
    validator_name, validator_module = _SCHEMA_VALIDATORS[schema_id]
    raw = _read_and_verify(schema_id)
    return {
        "schema_id": schema_id,
        "resource_name": _SCHEMA_RESOURCES[schema_id],
        "resource_package": _RESOURCE_PACKAGE,
        "resource_subpath": list(_RESOURCE_SUBPATH),
        "json_schema_id": _SCHEMA_JSON_IDS[schema_id],
        "json_schema_id_is_identifier_only": True,
        "json_schema_id_never_fetched": True,
        "validation_scope": _VALIDATION_SCOPE,
        "normative_validator": {
            "function": validator_name,
            "module": validator_module,
        },
        "required_external_bindings": list(_SCHEMA_REQUIRED_BINDINGS[schema_id]),
        "binding_behavior": _SCHEMA_BINDING_BEHAVIOR[schema_id],
        "sha256": "sha256:" + _SCHEMA_DIGESTS[schema_id],
        "bytes_length": len(raw),
        "is_ascii": True,
        "library_authenticates_authority": False,
        "authorized_to_execute": False,
        "provenance_verified": False,
        "authority_status": "external_unverified",
    }


def schema_catalog() -> List[Dict[str, Any]]:
    """Catalogo completo y ordenado (descriptores frescos)."""
    return [schema_descriptor(schema_id) for schema_id in schema_ids()]


def catalog_summary() -> Dict[str, Any]:
    """Resumen machine-readable del catalogo (paquete instalado, sin $id fetch)."""
    return {
        "schema_count": schema_count(),
        "schema_ids": schema_ids(),
        "validation_scope": _VALIDATION_SCOPE,
        "resource_package": _RESOURCE_PACKAGE,
        "resource_subpath": list(_RESOURCE_SUBPATH),
        "json_schema_ids_are_identifiers_only": True,
        "json_schema_ids_never_fetched": True,
        "library_authenticates_authority": False,
        "authorized_to_execute": False,
        "provenance_verified": False,
        "authority_status": "external_unverified",
    }


def validator_callable(schema_id: str):
    """Resuelve el validador Python normativo (lazy import; sin cycle)."""
    schema_id = _require_known_id(schema_id)
    name, module_name = _SCHEMA_VALIDATORS[schema_id]
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


def verify_schema_integrity() -> None:
    """Recomputa todos los digests y rechaza cualquier divergencia."""
    for schema_id in _SCHEMA_RESOURCES:
        _read_and_verify(schema_id)


def json_schema_id_of(schema_id: str) -> str:
    """El ``$id`` declarado (identificador opaco, nunca fetched)."""
    schema_id = _require_known_id(schema_id)
    return _SCHEMA_JSON_IDS[schema_id]


__all__ = [
    "SchemaError",
    "catalog_summary",
    "json_schema_id_of",
    "read_schema_bytes",
    "read_schema_document",
    "read_schema_text",
    "schema_catalog",
    "schema_count",
    "schema_descriptor",
    "schema_ids",
    "validator_callable",
    "verify_schema_integrity",
]
