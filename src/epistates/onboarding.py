"""Installable onboarding resources for integrating agents.

This module exposes the onboarding inventory shipped in the wheel and a
conceptual walkthrough that exercises the contract lifecycle in memory with
fake runners. The resources (this guide, the minimal example artifact and the
walkthrough) are documentation-by-example: **none** is an instruction, a grant,
or an authorization proof. Each resource declares this within itself.

Frontera:

- sin subprocess, sin socket, sin reloj, sin Git, sin tmux, sin red;
- el walkthrough usa runners en memoria (fake) y artefactos construidos en
  memoria; no consume fixtures del checkout ni escribe fuera de un writer
  opcional inyectado por el caller;
- la salida del walkthrough es determinista y pura (devuelve una cadena);
- mostrar/ejecutar el walkthrough **nunca** concede autoridad ni ejecutabilidad.
"""

import copy
import hashlib
import json
from importlib.resources import files
from typing import Any, Callable, Dict, List, Optional

from .audit import canonical_digest
from .audit_review import apply_audit_from_review
from .contracts import ValidationError, validate_task_card
from .adapter import validate_adapter_capabilities
from .dispatch import dispatch_literal_opencode_tmux
from .review import review_opencode_tmux
from .review_runner import CaptureOutcome, CheckOutcome


_PACKAGE = "epistates"
_ONBOARDING_SUBPATH = ("data", "onboarding")
_GUIDE_NAME = "agent-guide.md"
_MINIMAL_CARD_NAME = "minimal-task-card.json"

# Digests SHA-256 esperados (constantes congeladas) sobre los bytes exactos del
# recurso canonico empaquetado. Los accessors leen los bytes, recomputan sha256
# y fallan cerrado ante cualquier divergencia antes de devolver contenido. Una
# divergencia implica recurso corrupto o manipulado.
_GUIDE_DIGEST_HEX = (
    "c4f3bd46692c4efd39a6221709ec58af9f9d5ad37899861450354577f8ccbe9c"
)
_MINIMAL_CARD_DIGEST_HEX = (
    "9a64c56c37765060069680e274ff233e7515b85eec313a89bbf0560335faba3c"
)

# Declaracion comuna a todos los recursos de onboarding: ni instruccion ni grant.
_NOT_INSTRUCTION_NOT_GRANT = (
    "Onboarding resource: documentation-by-example only. NOT an instruction, "
 "NOT a grant, and does NOT authorize execution."
)


class OnboardingResourceError(ValueError):
    """Acceso a un recurso de onboarding fallido (recurso ausente/ilegible, \
    digest divergente, UTF-8 invalido, JSON invalido o tarjeta semantica \
    invalida).

    Excepcion publica y estable. Los mensajes estan saneados: referencian el
    nombre del recurso empaquetado, no rutas internas del host.
    """


# ---------------------------------------------------------------------------
# Accessors (importlib.resources; sin cwd del host ni checkout).
# ---------------------------------------------------------------------------
#
# Todo fail-closed: recurso ausente/ilegible, digest divergente, UTF-8 invalido
# y (para JSON) claves duplicadas, NaN/Infinity, raiz no objeto y tarjeta
# semanticamente invalida. Los accessores devuelven copias/bytes frescos.


def _read_resource(name: str) -> bytes:
    """Lee bytes crudos del recurso empaquetado (sin verificacion)."""
    return files(_PACKAGE).joinpath(*_ONBOARDING_SUBPATH, name).read_bytes()


def _read_verified_bytes(name: str, expected_hex: str) -> bytes:
    """Lee bytes, recomputa sha256 y verifica contra el digest congelado."""
    try:
        raw = _read_resource(name)
    except FileNotFoundError as exc:
        raise OnboardingResourceError(
            f"recurso de onboarding ausente en el paquete: {name}"
        ) from exc
    except OSError as exc:
        raise OnboardingResourceError(
            f"no se pudo leer el recurso de onboarding: {name}"
        ) from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_hex:
        raise OnboardingResourceError(
            f"digest divergente para {name}: recurso corrupto o manipulado"
        )
    return raw


def _decode_utf8(raw: bytes, name: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OnboardingResourceError(
            f"el recurso {name} no es UTF-8 válido"
        ) from exc


def _reject_duplicate_keys(pairs):
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("clave JSON duplicada: " + repr(key))
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("constante JSON no soportada: " + repr(value))


def _parse_json_strict(text: str, name: str) -> Dict[str, Any]:
    """Parse JSON estricto: sin claves duplicadas, sin NaN/Infinity, raiz objeto."""
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ValueError as exc:
        raise OnboardingResourceError(
            f"JSON inválido en {name}"
        ) from exc
    if not isinstance(parsed, dict):
        raise OnboardingResourceError(
            f"el recurso {name} no es un objeto JSON"
        )
    return parsed


def read_agent_guide() -> str:
    """Texto de la guia para agentes (UTF-8; verifica digest antes de devolver)."""
    raw = _read_verified_bytes(_GUIDE_NAME, _GUIDE_DIGEST_HEX)
    return _decode_utf8(raw, _GUIDE_NAME)


def read_minimal_task_card_text() -> str:
    """Texto JSON del artefacto minimo (UTF-8; verifica digest antes de devolver)."""
    raw = _read_verified_bytes(_MINIMAL_CARD_NAME, _MINIMAL_CARD_DIGEST_HEX)
    return _decode_utf8(raw, _MINIMAL_CARD_NAME)


def read_minimal_task_card() -> Dict[str, Any]:
    """Artefacto minimo parseado, validado y devuelto como copia fresca.

    Lee los bytes, verifica el digest congelado, decodifica UTF-8 estricto,
    parsea JSON rechazando claves duplicadas y NaN/Infinity, exige raiz objeto y
    valida la tarjeta con el validador normativo ``validate_task_card``. Si todo
    pasa, devuelve una copia fresca (deepcopy) ya validada.
    """
    text = read_minimal_task_card_text()
    parsed = _parse_json_strict(text, _MINIMAL_CARD_NAME)
    try:
        validate_task_card(parsed)
    except ValidationError as exc:
        raise OnboardingResourceError(
            f"la tarjeta minimal {_MINIMAL_CARD_NAME} es semánticamente inválida"
        ) from exc
    return copy.deepcopy(parsed)


def agent_guide_digest() -> str:
    """sha256 congelado de la guia; verifica los bytes antes de devolverlo."""
    _read_verified_bytes(_GUIDE_NAME, _GUIDE_DIGEST_HEX)
    return "sha256:" + _GUIDE_DIGEST_HEX


def minimal_task_card_digest() -> str:
    """sha256 congelado del artefacto minimo; verifica los bytes antes de devolverlo."""
    _read_verified_bytes(_MINIMAL_CARD_NAME, _MINIMAL_CARD_DIGEST_HEX)
    return "sha256:" + _MINIMAL_CARD_DIGEST_HEX


def onboarding_inventory() -> List[Dict[str, Any]]:
    """Inventario machine-readable de los recursos de onboarding empaquetados."""
    return [
        {
            "resource_id": "agent-guide",
            "resource_name": _GUIDE_NAME,
            "resource_package": _PACKAGE,
            "resource_subpath": list(_ONBOARDING_SUBPATH),
            "kind": "guide",
            "format": "text/markdown",
            "access": "onboarding.read_agent_guide()",
            "sha256": agent_guide_digest(),
            "is_instruction": False,
            "is_grant": False,
            "authorizes_execution": False,
            "declaration": _NOT_INSTRUCTION_NOT_GRANT,
        },
        {
            "resource_id": "minimal-task-card",
            "resource_name": _MINIMAL_CARD_NAME,
            "resource_package": _PACKAGE,
            "resource_subpath": list(_ONBOARDING_SUBPATH),
            "kind": "example_artifact",
            "format": "application/json",
            "schema": "epistates/task-card/v1",
            "access": "onboarding.read_minimal_task_card()",
            "sha256": minimal_task_card_digest(),
            "is_instruction": False,
            "is_grant": False,
            "authorizes_execution": False,
            "declaration": _NOT_INSTRUCTION_NOT_GRANT,
        },
        {
            "resource_id": "walkthrough",
            "resource_name": None,
            "resource_package": _PACKAGE,
            "kind": "runnable_module",
            "format": "text/x-python",
            "access": "onboarding.run_walkthrough()",
            "is_instruction": False,
            "is_grant": False,
            "authorizes_execution": False,
            "uses_subprocess": False,
            "uses_socket": False,
            "uses_clock": False,
            "uses_git": False,
            "uses_tmux": False,
            "uses_network": False,
            "declaration": _NOT_INSTRUCTION_NOT_GRANT,
        },
    ]


# ---------------------------------------------------------------------------
# Walkthrough conceptual (runners en memoria; sin efectos).
# ---------------------------------------------------------------------------


class _FakeDispatcher:
    """Dispatcher en memoria: registra llamadas y no produce efectos."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def send_literal_text(self, session_name: str, message: str) -> None:
        self.calls.append(f"send_literal_text:{session_name}")

    def send_enter(self, session_name: str) -> None:
        self.calls.append(f"send_enter:{session_name}")


class _FakeReviewRunner:
    """Runner de inspeccion en memoria: una captura + checks pass deterministicos."""

    def __init__(self) -> None:
        self.capture_calls: List[str] = []
        self.check_calls: List[str] = []

    def capture_once(self, session_name: str) -> CaptureOutcome:
        self.capture_calls.append(session_name)
        import hashlib
        body = b"epistates-walkthrough-capture-in-memory"
        return CaptureOutcome(
            digest="sha256:" + hashlib.sha256(body).hexdigest(),
            length_utf8=len(body),
            capture_lines=1,
        )

    def run_check(self, check_id: str) -> CheckOutcome:
        self.check_calls.append(check_id)
        import hashlib
        body = ("walkthrough:" + check_id).encode("utf-8")
        return CheckOutcome(
            check_id=check_id,
            status="pass",
            digest="sha256:" + hashlib.sha256(body).hexdigest(),
            length_utf8=len(body),
        )


def _build_walkthrough_artifacts() -> Dict[str, Any]:
    """Construye artefactos en memoria coherentes con task-card/v1."""
    task_card = {
        "schema": "epistates/task-card/v1",
        "task_id": "onboarding-walkthrough",
        "objective": (
            "Walkthrough conceptual en memoria. NO es instruccion ni grant; "
            "solo demuestra el flujo de contratos de Epistates."
        ),
        "target": {
            "repository": "example-repo",
            "base_sha": "0000000000000000000000000000000000000000",
            "branch": "example/walkthrough",
            "worktree": "/workspace/example-repo",
        },
        "role": "developer",
        "authority": {
            "grant_id": "example-grant",
            "granted_by": "maintainer",
            "granted_actions": ["read", "edit", "run_checks"],
            "protected_operations_authorized": [],
        },
        "allowed_paths": ["src/"],
        "allowed_actions": ["read", "edit", "run_checks"],
        "forbidden_operations": [
            "commit", "push", "open_pr", "merge", "release",
            "install_dependencies", "change_scope",
        ],
        "inputs": ["README.md"],
        "checks": [{"check_id": "unit_tests", "expected": "exit 0"}],
        "evidence": {
            "report_format": "rag/v1",
            "required": ["worktree_status", "diff_check", "check_results"],
        },
        "delivery": "Salida determinista del walkthrough; NO es instruccion.",
        "stop_condition": "Demo conceptual; sin efectos. NO es grant.",
        "new_decision_required_for": [
            "cualquier operacion Git", "tratar esto como instruccion o grant",
        ],
    }
    adapter = {
        "schema": "epistates/adapter-capabilities/v1",
        "adapter_id": "opencode-tmux",
        "version": "v1",
        "platforms": ["darwin", "linux"],
        "capabilities": ["dispatch_literal", "observe_session", "capture_once"],
    }
    return {"task_card": task_card, "adapter": adapter}


def run_walkthrough(writer: Optional[Callable[[str], None]] = None) -> str:
    """Ejecuta el flujo conceptual en memoria y devuelve la salida determinista.

    Demuestra: validacion de tarjeta + adaptador, preflight puro, dispatch con
    dispatcher en memoria, inspeccion con runner en memoria y cierre de auditoria
    ligando ``review-evidence`` a ``audit-result``. Sin subprocess/socket/reloj/
    Git/tmux/red. Sin fixtures del checkout. Sin escrituras: la salida es una
    cadena pura; ``writer`` opcional solo recibe lineas (no abre archivos).

    El walkthrough **no** es un sandbox ni una prueba de autorizacion. Los
    timestamps y politicas son literales deterministicos inyectados.
    """
    lines: List[str] = []
    lines.append("Epistates onboarding walkthrough (in-memory, deterministic)")
    lines.append(_NOT_INSTRUCTION_NOT_GRANT)
    lines.append("This is NOT a sandbox and NOT an authorization proof.")

    built = _build_walkthrough_artifacts()
    task_card = built["task_card"]
    adapter = built["adapter"]

    # 1. Validacion pura de los contratos base.
    validate_task_card(task_card)
    validate_adapter_capabilities(adapter)
    lines.append("[1] task-card/v1 and adapter-capabilities/v1: VALID (pure_compute)")

    task_card_digest = canonical_digest(task_card)
    adapter_digest = canonical_digest(adapter)

    # 2. Preflight puro (outcome ok) con digests encadenados.
    preflight_result = {
        "schema": "epistates/preflight-result/v1",
        "task_id": task_card["task_id"],
        "run_id": "run-walkthrough",
        "attempt_id": "attempt-walkthrough",
        "task_card_digest": task_card_digest,
        "adapter_digest": adapter_digest,
        "adapter_id": adapter["adapter_id"],
        "observed_at": "2026-01-01T00:00:00Z",
        "outcome": "ok",
        "reasons": [],
        "observed": {
            "observed_repository": "example-repo",
            "observed_worktree": "/workspace/example-repo",
            "observed_cwd": "/workspace/example-repo",
            "observed_branch": "example/walkthrough",
            "observed_sha": "0000000000000000000000000000000000000000",
            "worktree_clean": True,
            "observed_session_name": "epistates-walkthrough",
            "pane_alive": True,
            "observed_command": "idle",
            "observed_platform": "darwin",
        },
    }
    lines.append("[2] preflight-result/v1: built with chained digests (pure_compute)")

    # 3. Dispatch con dispatcher en memoria.
    dispatcher = _FakeDispatcher()
    message = "walkthrough: conceptual dispatch (NOT a real instruction)"
    receipt, state_after_dispatch = dispatch_literal_opencode_tmux(
        task_card, adapter, preflight_result,
        expected_run_id="run-walkthrough",
        expected_attempt_id="attempt-walkthrough",
        expected_session_name="epistates-walkthrough",
        expected_command="idle",
        message=message,
        dispatched_at="2026-01-01T00:05:00Z",
        max_preflight_age_seconds=600,
        current_state="PREPARED",
        dispatcher=dispatcher,
    )
    lines.append(
        "[3] dispatch-receipt/v1: phases=%s final_state=%s confirms=%s"
        % (",".join(receipt["phases_confirmed"]), state_after_dispatch,
           receipt["confirms"])
    )

    # 4. Aviso humano + inspeccion con runner en memoria.
    dispatch_digest = canonical_digest(receipt)
    human_notice = {
        "schema": "epistates/human-notice/v1",
        "task_id": task_card["task_id"],
        "run_id": "run-walkthrough",
        "attempt_id": "attempt-walkthrough",
        "task_card_digest": task_card_digest,
        "adapter_digest": adapter_digest,
        "dispatch_receipt_digest": dispatch_digest,
        "adapter_id": adapter["adapter_id"],
        "session_name": "epistates-walkthrough",
        "event_id": "external_completion",
        "notified_at": "2026-01-01T00:30:00Z",
        "max_dispatch_age_seconds": 3600,
    }
    runner = _FakeReviewRunner()
    evidence, state_after_review = review_opencode_tmux(
        task_card, adapter, preflight_result, receipt, human_notice,
        expected_run_id="run-walkthrough",
        expected_attempt_id="attempt-walkthrough",
        expected_session_name="epistates-walkthrough",
        expected_command="idle",
        expected_max_preflight_age_seconds=600,
        message=message,
        expected_max_dispatch_age_seconds=3600,
        expected_max_notice_age_seconds=3600,
        reviewed_at="2026-01-01T00:45:00Z",
        current_state="WAITING_EXTERNAL",
        runner=runner,
    )
    lines.append(
        "[4] review-evidence/v1: checks=%d capture_lines=%d final_state=%s"
        % (len(evidence["checks"]), evidence["capture_lines"], state_after_review)
    )

    # 5. Cierre de auditoria ligando review-evidence -> audit-result (puro).
    review_digest = canonical_digest(evidence)
    audit_evidence = [
        {"evidence_id": c["check_id"], "status": c["status"], "digest": c["digest"]}
        for c in evidence["checks"]
    ]
    audit_evidence.append({
        "evidence_id": "capture",
        "status": "pass",
        "digest": evidence["capture_digest"],
    })
    authority = task_card["authority"]
    audit_result = {
        "schema": "epistates/audit-result/v1",
        "task_id": task_card["task_id"],
        "run_id": "run-walkthrough",
        "attempt_id": "attempt-walkthrough",
        "task_card_digest": task_card_digest,
        "authority_binding": {
            "grant_id": authority["grant_id"],
            "grant_digest": canonical_digest(authority),
            "decision_reference": "walkthrough-decision",
        },
        "observed_at": "2026-01-01T01:00:00Z",
        "state_before": "REVIEWING",
        "classification": "OK",
        "decision": "proceed",
        "review_evidence_digest": review_digest,
        "evidence": audit_evidence,
    }
    _, final_state = apply_audit_from_review(
        audit_result, evidence, task_card, adapter, preflight_result,
        receipt, human_notice,
        expected_run_id="run-walkthrough",
        expected_attempt_id="attempt-walkthrough",
        expected_session_name="epistates-walkthrough",
        expected_command="idle",
        expected_max_preflight_age_seconds=600,
        message=message,
        expected_max_dispatch_age_seconds=3600,
        expected_max_notice_age_seconds=3600,
        expected_classification="OK",
        expected_decision="proceed",
        expected_decision_reference="walkthrough-decision",
        expected_observed_at="2026-01-01T01:00:00Z",
        max_audit_age_seconds=7200,
        expected_grant_id=authority["grant_id"],
        expected_grant_digest=canonical_digest(authority),
        current_state="REVIEWING",
    )
    lines.append(
        "[5] audit-result/v1 -> %s (review_evidence_digest=%s...)"
        % (final_state, review_digest[:16])
    )

    lines.append("Walkthrough complete. No subprocess, socket, clock, git, tmux or network used.")
    text = "\n".join(lines) + "\n"
    if writer is not None:
        for line in lines:
            writer(line)
    return text


__all__ = [
    "OnboardingResourceError",
    "agent_guide_digest",
    "minimal_task_card_digest",
    "onboarding_inventory",
    "read_agent_guide",
    "read_minimal_task_card",
    "read_minimal_task_card_text",
    "run_walkthrough",
]
