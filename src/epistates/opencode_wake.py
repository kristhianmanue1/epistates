"""Puerto mínimo para el API público local de OpenCode; no conoce Z.ai."""

import hashlib
import json
import re
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlparse


_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{3,128}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_GLM_MODEL = re.compile(r"glm-[a-z0-9.-]{2,80}")
_VERSION = re.compile(r"[0-9][A-Za-z0-9._-]{0,63}")
_PROMPT = "Controller requested a read-only status check. Do not execute commands or modify files."


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
                not isinstance(provider_version, str) or
                not _VERSION.fullmatch(provider_version) or
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
        """Comprueba sólo health y la existencia del agente configurado."""
        try:
            health = self._transport("GET", "/global/health", None)
            agents = self._transport("GET", "/agent", None)
        except Exception:
            return "failed"
        if (not isinstance(health, Mapping) or health.get("healthy") is not True or
                health.get("version") != self._provider_version):
            return "unsupported"
        if not isinstance(agents, list) or not any(
                isinstance(item, Mapping) and item.get("name") == self._agent_id
                for item in agents):
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
