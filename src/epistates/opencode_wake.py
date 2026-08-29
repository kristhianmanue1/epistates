"""Puerto mínimo para el API público local de OpenCode; no conoce Z.ai."""

import hashlib
import json
import posixpath
import re
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlparse


_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{3,128}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_GLM_MODEL = re.compile(r"glm-[a-z0-9.-]{2,80}")
_VERSION = re.compile(r"[0-9][A-Za-z0-9._-]{0,63}")
_PROMPT = "Controller requested a read-only status check. Do not execute commands or modify files."
_PERMISSION_NAME = re.compile(r"[A-Za-z0-9_.*-]{1,128}")
_MAX_PERMISSION_RULES = 256


def _safe_rule(rule: object) -> bool:
    if type(rule) is not dict or set(rule) != {"permission", "pattern", "action"}:
        return False
    permission = rule.get("permission")
    pattern = rule.get("pattern")
    action = rule.get("action")
    return bool(
        isinstance(permission, str) and
        _PERMISSION_NAME.fullmatch(permission) is not None and
        isinstance(pattern, str) and 1 <= len(pattern) <= 1024 and
        not any(ord(character) < 32 or ord(character) == 127 for character in pattern) and
        action in {"allow", "ask", "deny"}
    )


def _internal_truncation_rule(rule: dict) -> bool:
    pattern = rule["pattern"]
    if (rule["permission"] != "external_directory" or
            rule["action"] != "allow" or not pattern.startswith("/") or
            not pattern.endswith("/opencode/tool-output/*") or
            pattern.count("*") != 1 or any(token in pattern for token in ("?", "[", "]", "\\", "%2e", "%2E"))):
        return False
    base = pattern[:-2]
    return posixpath.normpath(base) == base and ".." not in base.split("/")


def _effective_agent_supported(agents: object, *, agent_id: str,
                               model_id: str) -> bool:
    """Valida el ruleset ordenado de OpenCode 1.18.25 sin ejecutar efectos."""
    if type(agents) is not list:
        return False
    matches = [item for item in agents
               if type(item) is dict and item.get("name") == agent_id]
    if len(matches) != 1:
        return False
    agent = matches[0]
    model = agent.get("model")
    rules = agent.get("permission")
    if (agent.get("mode") != "primary" or type(model) is not dict or
            set(model) != {"providerID", "modelID"} or
            model.get("providerID") != "zai" or model.get("modelID") != model_id or
            type(rules) is not list or not 1 <= len(rules) <= _MAX_PERMISSION_RULES or
            not all(_safe_rule(rule) for rule in rules)):
        return False

    global_denies = [index for index, rule in enumerate(rules)
                     if rule == {"permission": "*", "pattern": "*", "action": "deny"}]
    if not global_denies:
        return False
    tail = rules[global_denies[-1] + 1:]
    external_deny = {"permission": "external_directory", "pattern": "*",
                     "action": "deny"}
    if not tail:
        return True
    if tail[0] != external_deny or len(tail) > 2:
        return False
    return len(tail) == 1 or _internal_truncation_rule(tail[1])


def _message_id(nonce: str) -> str:
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise ValueError("nonce OpenCode no permitido")
    return "msg_e4_" + nonce


def _body(agent_id: str, model_id: str, nonce: str) -> dict:
    return {"messageID": _message_id(nonce), "agent": agent_id,
            "model": {"providerID": "zai", "modelID": model_id},
            "parts": [{"type": "text", "text": _PROMPT}]}


def _body_digest(agent_id: str, model_id: str, nonce: str) -> str:
    raw = json.dumps(_body(agent_id, model_id, nonce), sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class OpenCodeWakePort:
    """Allowlist de health, agent y prompt_async para un agente OpenCode."""

    def __init__(self, base_url: str, *, provider_version: str,
                 agent_id: str, model_id: str,
                 transport: Callable[[str, str, Optional[Mapping[str, Any]]], Any]):
        parsed = urlparse(base_url)
        try:
            transport_base = getattr(transport, "base_url", None)
        except Exception:
            transport_base = "invalid"
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or
                parsed.username is not None or parsed.password is not None or
                parsed.path not in {"", "/"} or parsed.query or parsed.fragment or
                provider_version != "1.18.25" or
                not isinstance(agent_id, str) or not _SESSION_ID.fullmatch(agent_id) or
                not isinstance(model_id, str) or not _GLM_MODEL.fullmatch(model_id) or
                not callable(transport) or
                (transport_base is not None and
                 transport_base.rstrip("/") != base_url.rstrip("/"))):
            raise ValueError("configuración OpenCode no permitida")
        self.base_url = base_url.rstrip("/")
        self._provider_id = "opencode-local"
        self._provider_version = provider_version
        self._agent_id = agent_id
        self._model_id = model_id
        self._transport = transport

    @property
    def provider_version(self) -> str:
        return self._provider_version

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def delivery_binding(self, nonce: str) -> dict:
        """Binding exacto del cuerpo correlacionado que se reservará."""
        return {
            "provider_id": self._provider_id,
            "provider_version": self._provider_version,
            "agent_id": self._agent_id,
            "model_id": self._model_id,
            "body_digest": _body_digest(self._agent_id, self._model_id, nonce),
        }

    def capabilities(self) -> str:
        """Comprueba health y el perfil efectivo deny-by-default del agente."""
        try:
            health = self._transport("GET", "/global/health", None)
            agents = self._transport("GET", "/agent", None)
        except Exception:
            return "failed"
        try:
            supported = (
                type(health) is dict and
                health.get("healthy") is True and
                health.get("version") == self._provider_version and
                _effective_agent_supported(
                    agents, agent_id=self._agent_id, model_id=self._model_id)
            )
        except Exception:
            supported = False
        if not supported:
            return "unsupported"
        return "supported"

    def request_wake(self, session_id: str, nonce: str) -> str:
        """Envía sólo el prompt fijo permitido; el caller debe tener reserva E4."""
        if (not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id) or
                not isinstance(nonce, str) or not _NONCE.fullmatch(nonce)):
            return "rejected"
        if self.capabilities() != "supported":
            return "unsupported"
        body = _body(self._agent_id, self._model_id, nonce)
        try:
            result = self._transport("POST", "/session/{}/prompt_async".format(session_id), body)
        except Exception:
            return "failed"
        return "queued" if result is None else "failed"


__all__ = ["OpenCodeWakePort"]
