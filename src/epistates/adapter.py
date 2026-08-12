"""Validacion read-only del contrato neutral ``epistates/adapter-capabilities/v1``.

El contrato declara identidad y capacidades de un adaptador; no prueba que las
capacidades esten implementadas. La neutralidad la garantizan los catalogos
cerrados y el enum de plataformas, no el nombre del ``adapter_id``: un valor como
``opencode-tmux`` identifica legitimamente el host concreto.
"""

import re
from typing import Any, Mapping

from .capabilities import CAPABILITY_IDS
from .contracts import ValidationError


_ADAPTER_FIELDS = frozenset({
    "schema", "adapter_id", "version", "platforms", "capabilities",
})
_ADAPTER_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,63}")
_PLATFORMS = frozenset({"darwin", "linux"})
# IDs canonicos desde la fuente neutral publica ``epistates.capabilities``.
_CAPABILITY_IDS = CAPABILITY_IDS


def _require_nonempty_str(value: Any, field: str) -> None:
    if (not isinstance(value, str) or not value.strip()
            or any(0xD800 <= ord(character) <= 0xDFFF for character in value)):
        raise ValidationError(f"{field} debe ser texto no vacio")


def _require_unique_enum_list(value: Any, field: str, allowed: frozenset) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} debe ser una lista no vacia")
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise ValidationError(f"{field} contiene un valor no soportado")
        if item in seen:
            raise ValidationError(f"{field} contiene un valor duplicado")
        seen.add(item)


def validate_adapter_capabilities(capabilities: Mapping[str, Any]) -> None:
    """Comprueba forma y garantias minimas de ``adapter-capabilities/v1``."""
    if not isinstance(capabilities, Mapping):
        raise ValidationError("el adaptador debe ser un objeto JSON")
    missing = _ADAPTER_FIELDS - capabilities.keys()
    unknown = capabilities.keys() - _ADAPTER_FIELDS
    if missing:
        raise ValidationError(f"campos requeridos ausentes: {', '.join(sorted(missing))}")
    if unknown:
        rendered = ", ".join(repr(field) for field in sorted(unknown))
        raise ValidationError(f"campos no permitidos: {rendered}")
    if capabilities["schema"] != "epistates/adapter-capabilities/v1":
        raise ValidationError("schema debe ser epistates/adapter-capabilities/v1")
    adapter_id = capabilities["adapter_id"]
    if not isinstance(adapter_id, str) or not _ADAPTER_ID_PATTERN.fullmatch(adapter_id):
        raise ValidationError("adapter_id debe usar minusculas, digitos o guiones (3-64 caracteres)")
    if capabilities["version"] != "v1":
        raise ValidationError("version debe ser v1")
    _require_unique_enum_list(capabilities["platforms"], "platforms", _PLATFORMS)
    _require_unique_enum_list(capabilities["capabilities"], "capabilities", _CAPABILITY_IDS)
