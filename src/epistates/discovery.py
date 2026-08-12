"""Superficie de descubrimiento estático ``epistates/discovery/v1``.

Este módulo construye el documento de descubrimiento de forma **estática y
determinista**: no ejecuta subprocess, no abre sockets, no lee el reloj, no
consulta la plataforma, no inspecciona el host ni consulta un adaptador vivo.

Frontera que este documento respeta (y representa machine-readable):

```text
descrito != implementado != observado != autorizado
schema-válido != semánticamente-válido != ligado != ejecutable
ejemplo != instrucción != grant
```

Aislamiento: ``build_discovery_document`` devuelve una estructura **totalmente
nueva** (``copy.deepcopy``). Mutar agresivamente cualquier dict/list anidado de
una respuesta no puede alterar respuestas posteriores ni las constantes internas
del módulo.

Autoridad y provenance: ``task-card.authority`` es **solo correlación
autodeclarable**; la autoridad vigente llega de un control-plane/canal externo
autenticado y se LIGA con los campos de la tarjeta. Epistates **NO autentica
grants**: sólo compara bindings. Cada operación declara ``authority_enforcement``
que distingue ``not_required`` de ``external_control_plane`` /
``caller_responsibility``.

El documento es **dato, no autoridad**.
"""

import copy
from typing import Any, Dict, List

from ._version import __version__
from .capabilities import CAPABILITY_IDS, capability_descriptors


DISCOVERY_SCHEMA = "epistates/discovery/v1"

# Schemas que ``epistates validate`` sabe validar. Hay un test de paridad
# exacta contra ``epistates.__main__._VALIDATORS`` para evitar derivas.
_SCHEMAS_VALIDATABLE: List[str] = [
    "epistates/task-card/v1",
    "epistates/audit-result/v1",
    "epistates/adapter-capabilities/v1",
    "epistates/preflight-result/v1",
    "epistates/dispatch-receipt/v1",
    "epistates/human-notice/v1",
    "epistates/review-evidence/v1",
]

# Schemas que ``epistates`` EMITE como salida (no son inputs validables).
# Slice2: ``validate --format json`` produce ``epistates/validation-report/v1``.
# ``epistates/discovery/v1`` lo emite ``describe --format json``.
_SCHEMAS_OUTPUT: List[str] = [
    "epistates/discovery/v1",
    "epistates/validation-report/v1",
]

_ANY_PLATFORM = ("any",)
_TMUX_PLATFORMS = ("darwin", "linux")

_EFFECT_CLASSES: List[str] = [
    "pure_compute",
    "filesystem_read",
    "host_observation",
    "terminal_write",
    "project_code_execution",
]
_RETRY_SAFETY_CLASSES: List[str] = [
    "safe_to_retry",
    "not_safe_indeterminate_or_partial",
    "not_safe_single_shot",
]
_INVOCATION_MODES: List[str] = ["composite_subcommand", "library_only"]
# Cómo se obtiene/aplica la autoridad. Epistates NO autentica grants.
_AUTHORITY_ENFORCEMENT: List[str] = [
    "not_required",
    "external_control_plane",
    "caller_responsibility",
]
_BINDING_BEHAVIORS: List[str] = ["none", "structural_only", "correlation_only"]
_SYMBOL_KINDS: List[str] = ["metadata", "type", "error", "operation"]
_PLANE_STATUS: List[str] = [
    "populated_statically",
    "not_populated_statically",
]
_IMPLEMENTATION_SIGNALS: List[str] = [
    "implemented_in_source",
    "not_observed",
]

_PYTHON_MIN = "3.9"


# ---------------------------------------------------------------------------
# Helpers de construcción.
# ---------------------------------------------------------------------------


def _host_method(name: str) -> Dict[str, Any]:
    executable = "git" if name.startswith("git_") else "tmux"
    return {
        "name": name,
        "effect_class": "host_observation",
        "requires_external_authority": True,
        "may_mutate_host": False,
        "retry_safety": "not_safe_single_shot",
        "platforms": list(_TMUX_PLATFORMS),
        "executables": [executable],
        "executable_requirement": "all_of",
    }


_RUNNER_METHODS: Dict[str, Dict[str, Any]] = {
    "git_toplevel": _host_method("git_toplevel"),
    "git_head": _host_method("git_head"),
    "git_branch": _host_method("git_branch"),
    "git_status": _host_method("git_status"),
    "tmux_list_panes": _host_method("tmux_list_panes"),
    "send_literal_text": {
        "name": "send_literal_text",
        "effect_class": "terminal_write",
        "requires_external_authority": True,
        "may_mutate_host": True,
        "retry_safety": "not_safe_indeterminate_or_partial",
        "platforms": list(_TMUX_PLATFORMS),
        "executables": ["tmux"],
        "executable_requirement": "all_of",
    },
    "send_enter": {
        "name": "send_enter",
        "effect_class": "terminal_write",
        "requires_external_authority": True,
        "may_mutate_host": True,
        "retry_safety": "not_safe_indeterminate_or_partial",
        "platforms": list(_TMUX_PLATFORMS),
        "executables": ["tmux"],
        "executable_requirement": "all_of",
    },
    "capture_once": {
        "name": "capture_once",
        "effect_class": "host_observation",
        "requires_external_authority": True,
        "may_mutate_host": False,
        "retry_safety": "not_safe_single_shot",
        "platforms": list(_TMUX_PLATFORMS),
        "executables": ["tmux"],
        "executable_requirement": "all_of",
    },
    "run_check": {
        "name": "run_check",
        "effect_class": "project_code_execution",
        "requires_external_authority": True,
        "may_mutate_host": True,
        "retry_safety": "not_safe_single_shot",
        "platforms": list(_TMUX_PLATFORMS),
        "executables": ["git", "python"],
        "executable_requirement": "conditional_by_check_id",
        "executables_by_check_id": {
            "git_status": ["git"],
            "diff_check": ["git"],
            "unit_tests": ["python"],
        },
    },
}

_HOST_RUNNER_METHODS = [
    _RUNNER_METHODS["git_toplevel"],
    _RUNNER_METHODS["git_head"],
    _RUNNER_METHODS["git_branch"],
    _RUNNER_METHODS["git_status"],
    _RUNNER_METHODS["tmux_list_panes"],
]
_LITERAL_DISPATCHER_METHODS = [
    _RUNNER_METHODS["send_literal_text"],
    _RUNNER_METHODS["send_enter"],
]
_REVIEW_RUNNER_METHODS = [
    _RUNNER_METHODS["capture_once"],
    _RUNNER_METHODS["run_check"],
]


def _cli(mode: str, subcommand) -> Dict[str, Any]:
    # library_only serializa subcommand como null (None), no string vacío.
    return {
        "mode": mode,
        "subcommand": subcommand,
        "directly_invocable": False,
    }


_LIB = _cli("library_only", None)
_VAL = _cli("composite_subcommand", "validate")
_DSC = _cli("composite_subcommand", "describe")


# ---------------------------------------------------------------------------
# Superficie CLI conocida estáticamente (con effect/authority/mutation/retry).
# ---------------------------------------------------------------------------

_CLI_SURFACE: List[Dict[str, Any]] = [
    {
        "name": "--version",
        "kind": "flag",
        "effect_class": "pure_compute",
        "requires_external_authority": False,
        "may_mutate_host": False,
        "authority_enforcement": "not_required",
        "library_authenticates_authority": False,
        "binding_behavior": "none",
        "retry_safety": "safe_to_retry",
        "description": (
            "Imprime la version single-source del paquete y termina exit 0. "
            "Estatico: no sondea el host ni abre sockets."
        ),
    },
    {
        "name": "--help",
        "kind": "flag",
        "effect_class": "pure_compute",
        "requires_external_authority": False,
        "may_mutate_host": False,
        "authority_enforcement": "not_required",
        "library_authenticates_authority": False,
        "binding_behavior": "none",
        "retry_safety": "safe_to_retry",
        "description": "Imprime la ayuda estatica. No inicia procesos externos.",
    },
    {
        "name": "validate",
        "kind": "subcommand",
        "effect_class": "filesystem_read",
        "requires_external_authority": True,
        "may_mutate_host": False,
        "authority_enforcement": "caller_responsibility",
        "library_authenticates_authority": False,
        "binding_behavior": "correlation_only",
        "retry_safety": "safe_to_retry",
        "description": (
            "Lee artefactos JSON del filesystem y valida forma + binding. Hace "
            "I/O de archivos (filesystem_read); el acceso a las rutas requiere "
            "autoridad del caller (filesystem). No es pure_compute ni "
            "equivalente a las funciones validate_* sobre objetos ya cargados. "
            "La validez no es autorizacion. --format text (default) conserva "
            "las cadenas VALID/INVALID; --format json emite un unico objeto "
            "ASCII-escapado epistates/validation-report/v1 con taxonomia de "
            "errores cerrada y exits 0/1/2. Todo archivo (artefacto, bindings, "
            "message-file) pasa por el mismo loader seguro: solo regular, "
            "lectura acotada y anti-TOCTOU."
        ),
    },
    {
        "name": "describe",
        "kind": "subcommand",
        "effect_class": "pure_compute",
        "requires_external_authority": False,
        "may_mutate_host": False,
        "authority_enforcement": "not_required",
        "library_authenticates_authority": False,
        "binding_behavior": "none",
        "retry_safety": "safe_to_retry",
        "description": (
            "Emite el documento estatico epistates/discovery/v1 a stdout "
            "(ASCII-escapado, determinista). Estatico: no sondea el host."
        ),
    },
]


# ---------------------------------------------------------------------------
# Catalogo de simbolos publicos (debe coincidir exactamente con ``__all__``).
# ---------------------------------------------------------------------------

_METADATA: List[Dict[str, str]] = [
    {
        "name": "__version__",
        "kind": "metadata",
        "module": "epistates._version",
        "description": (
            "Fuente unica de la version del paquete (PEP 440). El tag humano "
            "candidato y la publicacion requieren autorizacion del mantenedor."
        ),
    },
]

_TYPES: List[Dict[str, Any]] = [
    {
        "name": "HostRunner",
        "kind": "type",
        "module": "epistates.host_runner",
        "nature": "protocol",
        "effect_class": "host_observation",
        "methods": [dict(m) for m in _HOST_RUNNER_METHODS],
        "description": (
            "Protocolo del runner de observacion del host (git y tmux). Todo "
            "contacto con el host requiere autoridad externa; ningun metodo "
            "acepta argv del caller."
        ),
    },
    {
        "name": "LiteralDispatcher",
        "kind": "type",
        "module": "epistates.dispatch",
        "nature": "protocol",
        "effect_class": "terminal_write",
        "methods": [dict(m) for m in _LITERAL_DISPATCHER_METHODS],
        "description": (
            "Protocolo del dispatcher con efecto de escritura limitado a "
            "tmux send-keys. Requiere autoridad y muta el terminal."
        ),
    },
    {
        "name": "ReviewRunner",
        "kind": "type",
        "module": "epistates.review_runner",
        "nature": "protocol",
        "effect_class": "project_code_execution",
        "methods": [dict(m) for m in _REVIEW_RUNNER_METHODS],
        "description": (
            "Protocolo del runner de inspeccion. capture_once y los checks de "
            "git son read-only; run_check puede ejecutar unit_tests (codigo "
            "del proyecto) y por eso NO es read-only."
        ),
    },
    {
        "name": "ProductionHostRunner",
        "kind": "type",
        "module": "epistates.host_runner",
        "nature": "concrete_class",
        "effect_class": "host_observation",
        "methods": [dict(m) for m in _HOST_RUNNER_METHODS],
        "description": (
            "Runner de produccion de observacion contra git y tmux. subprocess "
            "con shell=False, entorno minimo y argv cerrado. Todo contacto "
            "requiere autoridad externa."
        ),
    },
    {
        "name": "TmuxLiteralDispatcher",
        "kind": "type",
        "module": "epistates.dispatch",
        "nature": "concrete_class",
        "effect_class": "terminal_write",
        "methods": [dict(m) for m in _LITERAL_DISPATCHER_METHODS],
        "description": (
            "Dispatcher de produccion: dos llamadas tmux send-keys (literal + "
            "Enter). Unica frontera con escritura en terminal."
        ),
    },
    {
        "name": "TmuxReviewRunner",
        "kind": "type",
        "module": "epistates.review_runner",
        "nature": "concrete_class",
        "effect_class": "project_code_execution",
        "methods": [dict(m) for m in _REVIEW_RUNNER_METHODS],
        "description": (
            "Runner de inspeccion de produccion: capture-pane acotada + checks. "
            "run_check(unit_tests) ejecuta codigo del proyecto y muta; NO es "
            "read-only."
        ),
    },
    {
        "name": "PaneObservation",
        "kind": "type",
        "module": "epistates.host_runner",
        "nature": "named_tuple",
        "effect_class": "pure_compute",
        "description": "Metadata de un pane tmux observado. Dato inerte.",
    },
    {
        "name": "CaptureOutcome",
        "kind": "type",
        "module": "epistates.review_runner",
        "nature": "named_tuple",
        "effect_class": "pure_compute",
        "description": (
            "Metadata de captura (digest, longitud, lineas). El contenido "
            "capturado nunca sale del runner."
        ),
    },
    {
        "name": "CheckOutcome",
        "kind": "type",
        "module": "epistates.review_runner",
        "nature": "named_tuple",
        "effect_class": "pure_compute",
        "description": "Resultado de un check (pass/fail + digest + longitud).",
    },
    {
        "name": "PreflightResult",
        "kind": "type",
        "module": "epistates.preflight",
        "nature": "typed_dict",
        "effect_class": "pure_compute",
        "description": "Estructura del resultado portable preflight-result/v1.",
    },
]

_ERRORS: List[Dict[str, str]] = [
    {
        "name": "ValidationError",
        "kind": "error",
        "module": "epistates.contracts",
        "description": "Un artefacto no satisface su contrato declarado.",
    },
    {
        "name": "TransitionError",
        "kind": "error",
        "module": "epistates.state",
        "description": "Una transicion no pertenece al protocolo o carece de auditoria.",
    },
    {
        "name": "PreflightError",
        "kind": "error",
        "module": "epistates.preflight",
        "description": "Una observacion inyectada esta ausente o mal tipada.",
    },
    {
        "name": "HostObserverError",
        "kind": "error",
        "module": "epistates.host_runner",
        "description": "La observacion del host no pudo verificarse.",
    },
    {
        "name": "DispatchError",
        "kind": "error",
        "module": "epistates.dispatch",
        "description": "Fallo pre-efecto de dispatch: nada se intento enviar.",
    },
    {
        "name": "IndeterminateDispatchError",
        "kind": "error",
        "module": "epistates.dispatch",
        "description": "Fase 1 intentada ambiguamente; NO reintenta.",
    },
    {
        "name": "PartialDispatchError",
        "kind": "error",
        "module": "epistates.dispatch",
        "description": "Literal confirmado, Enter indeterminado; NO reintenta.",
    },
    {
        "name": "HumanNoticeError",
        "kind": "error",
        "module": "epistates.human_notice",
        "description": "El aviso humano no satisface su contrato o su ligadura.",
    },
    {
        "name": "ReviewError",
        "kind": "error",
        "module": "epistates.review",
        "description": "Fallo pre-efecto de inspeccion: nada se capturo ni ejecuto.",
    },
    {
        "name": "ReviewRunnerError",
        "kind": "error",
        "module": "epistates.review_runner",
        "description": (
            "La inspeccion no pudo completarse de forma verificable. Puede "
            "involucrar ejecucion de codigo del proyecto (unit_tests)."
        ),
    },
    {
        "name": "IndeterminateReviewError",
        "kind": "error",
        "module": "epistates.review_runner",
        "description": "Captura o check intentado ambiguamente; NO reintenta.",
    },
    {
        "name": "AuditReviewError",
        "kind": "error",
        "module": "epistates.audit_review",
        "description": "Fallo pre-efecto al ligar audit-result con review-evidence.",
    },
]


def _op(
    name: str, module: str, effect_class: str, requires_external_authority: bool,
    may_mutate_host: bool, retry_safety: str, authority_enforcement: str,
    cli: Dict[str, Any], description: str, platforms: tuple = _ANY_PLATFORM,
    binding_behavior: str = "none",
) -> Dict[str, Any]:
    return {
        "name": name,
        "kind": "operation",
        "module": module,
        "effect_class": effect_class,
        "requires_external_authority": requires_external_authority,
        "may_mutate_host": may_mutate_host,
        "retry_safety": retry_safety,
        "authority_enforcement": authority_enforcement,
        "library_authenticates_authority": False,
        "binding_behavior": binding_behavior,
        "cli_exposure": dict(cli),
        "platforms": list(platforms),
        "description": description,
    }


# Valor por defecto: autoridad no requerida para validadores/digest/discovery puros.
_NR = "not_required"
# Operaciones que requieren autoridad de un control-plane/canal externo autenticado.
# Epistates NO autentica grants; solo compara bindings.
_ECP = "external_control_plane"
# El resultado es una propuesta; aplicarlo operativamente es responsabilidad del
# caller y requiere autoridad externa.
_CR = "caller_responsibility"


_OPERATIONS: List[Dict[str, Any]] = [
    _op("validate_task_card", "epistates.contracts", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Validacion Python pura de task-card/v1 (sobre dict ya cargado).",
        binding_behavior="structural_only"),
    _op("validate_adapter_capabilities", "epistates.adapter", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Validacion Python pura de adapter-capabilities/v1.",
        binding_behavior="structural_only"),
    _op("validate_audit_result", "epistates.audit", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Validacion estructural Python pura de audit-result/v1.",
        binding_behavior="structural_only"),
    _op("validate_audit_binding", "epistates.audit", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Liga audit-result, tarjeta, grant y evidencia exigida; solo prueba "
        "correlacion, no autentica autoridad.", binding_behavior="correlation_only"),
    _op("validate_preflight_result", "epistates.preflight", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Validacion estructural Python pura de preflight-result/v1.",
        binding_behavior="structural_only"),
    _op("validate_preflight_binding", "epistates.preflight", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Liga preflight, tarjeta, adaptador y expectativas del controlador; "
        "solo correlaciona, no autentica autoridad.",
        binding_behavior="correlation_only"),
    _op("evaluate_preflight", "epistates.preflight", "pure_compute",
        False, False, "safe_to_retry", _NR, _LIB,
        "Evalua el preflight puro y fail-closed con observaciones inyectadas. "
        "No subprocess, no reloj."),
    _op("validate_dispatch_receipt", "epistates.dispatch", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Validacion estructural Python pura de dispatch-receipt/v1.",
        binding_behavior="structural_only"),
    _op("validate_dispatch_receipt_binding", "epistates.dispatch", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Liga recibo, tarjeta, adaptador, preflight exacto y mensaje; solo "
        "correlaciona, no autentica autoridad.",
        binding_behavior="correlation_only"),
    _op("validate_human_notice", "epistates.human_notice", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Validacion estructural Python pura de human-notice/v1.",
        binding_behavior="structural_only"),
    _op("validate_human_notice_binding", "epistates.human_notice", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Liga aviso, tarjeta, adaptador y dispatch receipt exacto; solo "
        "correlaciona, no autentica autoridad.",
        binding_behavior="correlation_only"),
    _op("validate_review_evidence", "epistates.review", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Validacion estructural Python pura de review-evidence/v1.",
        binding_behavior="structural_only"),
    _op("validate_review_evidence_binding", "epistates.review", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Liga evidencia a la cadena completa con politicas externas; solo "
        "correlaciona, no autentica autoridad.",
        binding_behavior="correlation_only"),
    _op("validate_audit_review_binding", "epistates.audit_review", "pure_compute",
        False, False, "safe_to_retry", _NR, _VAL,
        "Liga audit-result a review-evidence, decision, timestamp y autoridad "
        "inyectadas. Compara bindings; NO autentica grants.",
        binding_behavior="correlation_only"),
    _op("canonical_digest", "epistates.audit", "pure_compute",
        False, False, "safe_to_retry", _NR, _LIB,
        "Huella sha256 canonica (JSON determinista) de un artefacto."),
    _op("transition", "epistates.state", "pure_compute",
        True, False, "safe_to_retry", _CR, _LIB,
        "Computa una transicion propuesta de la maquina de estados pura. Puede "
        "derivar BLOCKED: aplicar/usar su resultado operativamente es "
        "responsabilidad del caller y requiere autoridad externa. Coherente "
        "con apply_audit*: la funcion no se auto-aplica."),
    _op("apply_audit", "epistates.state", "pure_compute",
        True, False, "safe_to_retry", _ECP, _LIB,
        "Finaliza REVIEWING mediante un resultado auditado. Tecnicamente pura, "
        "pero requiere autoridad externa para cerrar estado: consume un "
        "authority_binding (correlacion) y deriva DONE/CORRECTION_SENT/BLOCKED. "
        "Epistates NO autentica el grant; compara bindings.",
        binding_behavior="correlation_only"),
    _op("apply_audit_from_review", "epistates.audit_review", "pure_compute",
        True, False, "safe_to_retry", _ECP, _LIB,
        "Cierra la auditoria ligando review-evidence al audit-result exacto "
        "antes de apply_audit. Tecnicamente pura; requiere autoridad externa "
        "(decision, autoridad y timestamp inyectados) para cerrar estado. La "
        "libreria no autentica esa autoridad.", binding_behavior="correlation_only"),
    _op("observe_opencode_tmux", "epistates.host_observer", "host_observation",
        True, False, "not_safe_single_shot", _ECP, _LIB,
        "Observa git y tmux read-only via runner inyectado. Todo contacto con "
        "el host requiere autoridad externa aunque sea read-only. No autoriza "
        "ni entrega instrucciones.", _TMUX_PLATFORMS),
    _op("dispatch_literal_opencode_tmux", "epistates.dispatch", "terminal_write",
        True, True, "not_safe_indeterminate_or_partial", _ECP, _LIB,
        "Entrega literal via tmux send-keys. Requiere preflight ok, estado "
        "PREPARED y politica de frescura externa. Transporte tecnico no "
        "implica comprension; un resultado indeterminado o parcial NO es "
        "seguro para reintento.", _TMUX_PLATFORMS),
    _op("review_opencode_tmux", "epistates.review", "project_code_execution",
        True, True, "not_safe_single_shot", _ECP, _LIB,
        "Inspeccion fail-closed tras aviso humano: una captura y cada check "
        "una vez, sin reintento. run_check(unit_tests) ejecuta codigo del "
        "proyecto y NO es read-only; capture_once y los checks de git si lo "
        "son. Requiere estado WAITING_EXTERNAL y cadena completa.",
        _TMUX_PLATFORMS),
    _op("build_discovery_document", "epistates.discovery", "pure_compute",
        False, False, "safe_to_retry", _NR, _DSC,
        "Construye el documento estatico epistates/discovery/v1. Motor del "
        "subcomando 'describe --format json'; no sondea el host."),
]


def _ordered_symbols() -> List[Dict[str, Any]]:
    pool = list(_METADATA) + list(_TYPES) + list(_ERRORS) + list(_OPERATIONS)
    pool.sort(key=lambda item: item["name"])
    return pool


def cataloged_symbol_names() -> List[str]:
    return [item["name"] for item in _ordered_symbols()]


def capability_ids() -> List[str]:
    """IDs canonicos de capabilities desde la fuente canonica (capabilities.py)."""
    return sorted(CAPABILITY_IDS)


def validatable_schemas() -> List[str]:
    return list(_SCHEMAS_VALIDATABLE)


def output_schemas() -> List[str]:
    """Schemas que ``epistates`` emite como salida (no son inputs validables)."""
    return list(_SCHEMAS_OUTPUT)


def build_discovery_document() -> Dict[str, Any]:
    """Construye ``epistates/discovery/v1`` estatica, deterministicamente y aislada.

    Devuelve una estructura **totalmente nueva** (``copy.deepcopy``): mutar
    agresivamente cualquier dict/list anidado de la respuesta no altera
    respuestas posteriores ni las constantes internas del modulo.
    """
    document = {
        "schema": DISCOVERY_SCHEMA,
        "discovery_version": "v1",
        "package_version": __version__,
        "declarations": {
            "not_authority": True,
            "not_observed": True,
            "performs_host_probing": False,
            "static_only": True,
            "epistates_authenticates_grants": False,
            "summary": (
                "Descripcion estatica de la superficie instalada. No es "
                "autoridad, no es observacion del host y no realiza probing. "
                "Nunca concluye disponibilidad, vigencia o autorizacion."
            ),
        },
        "authority_provenance": {
            "task_card_authority": "self_declarable_correlation_only",
            "vigent_authority_source": "external_control_plane",
            "epistates_authenticates_grants": False,
            "description": (
                "task-card.authority es solo correlacion autodeclarable; la "
                "autoridad vigente llega de un control-plane/canal externo "
                "autenticado y se LIGA con los campos de la tarjeta. Epistates "
                "NO autentica grants; solo compara bindings."
            ),
        },
        "capability_planes": {
            "catalog": {
                "status": "populated_statically",
                "description": (
                    "Schemas, superficie CLI, capabilities y simbolos publicos "
                    "conocidos desde el paquete instalado."
                ),
                "schemas_validatable": list(_SCHEMAS_VALIDATABLE),
                "schemas_output": list(_SCHEMAS_OUTPUT),
                "document_schema": DISCOVERY_SCHEMA,
                "adapter_capabilities": capability_descriptors(),
                "cli_surface": [dict(e) for e in _CLI_SURFACE],
                "public_symbol_count": len(_ordered_symbols()),
            },
            "adapter_declaration": {
                "status": "not_populated_statically",
                "description": (
                    "Un adaptador declara identidad y capacidades via "
                    "adapter-capabilities/v1. El descubrimiento no consulta un "
                    "adaptador vivo; la presencia de un adapter_id o una "
                    "capability en el catalogo no implica implementado, "
                    "disponible ni autorizado."
                ),
            },
            "host_observation": {
                "status": "not_populated_statically",
                "description": (
                    "La observacion del host (git/tmux) la inyecta el "
                    "controlador en runtime. performs_host_probing es false."
                ),
            },
            "task_grant": {
                "status": "not_populated_statically",
                "description": (
                    "La autoridad vigente procede exclusivamente de un "
                    "control-plane/canal externo autenticado. El bloque "
                    "task-card.authority es correlacion autodeclarable: no "
                    "concede autoridad y este descubrimiento no la verifica."
                ),
            },
        },
        "implementation": {
            "code_in_package": "implemented_in_source",
            "host_runtime_available": "not_observed",
            "adapter_live": "not_observed",
            "authority_granted": "not_observed",
            "description": (
                "Representacion conservadora de descrito != implementado != "
                "observado != autorizado. Las operaciones estan implementadas "
                "en el codigo del paquete; eso no implica que el host tenga "
                "git/tmux, que un adaptador este vivo, ni que exista grant "
                "vigente."
            ),
        },
        "enums": {
            "effect_class": list(_EFFECT_CLASSES),
            "retry_safety": list(_RETRY_SAFETY_CLASSES),
            "invocation_mode": list(_INVOCATION_MODES),
            "authority_enforcement": list(_AUTHORITY_ENFORCEMENT),
            "binding_behavior": list(_BINDING_BEHAVIORS),
            "symbol_kind": list(_SYMBOL_KINDS),
            "capability_plane_status": list(_PLANE_STATUS),
            "implementation_signal": list(_IMPLEMENTATION_SIGNALS),
        },
        "runtime_requirements": {
            "python_min": _PYTHON_MIN,
            "python_min_source": "declared_package_metadata",
            "platforms_by_effect_class": {
                "pure_compute": list(_ANY_PLATFORM),
                "filesystem_read": list(_ANY_PLATFORM),
                "host_observation": list(_TMUX_PLATFORMS),
                "terminal_write": list(_TMUX_PLATFORMS),
                "project_code_execution": list(_TMUX_PLATFORMS),
            },
            "potential_executables_by_effect_class": {
                "pure_compute": [],
                "filesystem_read": [],
                "host_observation": ["git", "tmux"],
                "terminal_write": ["tmux"],
                "project_code_execution": ["git", "tmux", "python"],
            },
            "potential_executables_semantics": (
                "Union informativa, no requisito all_of. Los requisitos exactos "
                "se publican por metodo y dependen de la operacion/check."
            ),
        },
        "public_api": {
            "metadata": [dict(e) for e in _METADATA],
            "types": [dict(e) for e in _TYPES],
            "errors": [dict(e) for e in _ERRORS],
            "operations": [dict(e) for e in _OPERATIONS],
        },
    }
    # Aislamiento total: la respuesta no comparte referencias con constantes.
    return copy.deepcopy(document)


def render_discovery_json() -> str:
    """Serializa el documento a JSON determinista, ASCII-escapado y robusto."""
    import json

    document = build_discovery_document()
    return json.dumps(document, ensure_ascii=True, indent=2) + "\n"
