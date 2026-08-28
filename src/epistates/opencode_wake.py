"""Puerto mínimo para el API público local de OpenCode; no conoce Z.ai."""

import re
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlparse


_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{3,128}")
_GLM_MODEL = re.compile(r"glm-[a-z0-9.-]{2,80}")
_PROMPT = "Controller requested a read-only status check. Do not execute commands or modify files."


class OpenCodeWakePort:
    """Allowlist de health, agent y prompt_async para un agente OpenCode."""

    def __init__(self, base_url: str, *, agent_id: str, model_id: str,
                 transport: Callable[[str, str, Optional[Mapping[str, Any]]], Any]):
        parsed = urlparse(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or
                parsed.path not in {"", "/"} or parsed.query or parsed.fragment or
                not isinstance(agent_id, str) or not _SESSION_ID.fullmatch(agent_id) or
                not isinstance(model_id, str) or not _GLM_MODEL.fullmatch(model_id) or
                not callable(transport)):
            raise ValueError("configuración OpenCode no permitida")
        self.base_url, self.agent_id, self.model_id, self._transport = base_url.rstrip("/"), agent_id, model_id, transport

    def capabilities(self) -> str:
        """Comprueba sólo health y la existencia del agente configurado."""
        try:
            health = self._transport("GET", "/global/health", None)
            agents = self._transport("GET", "/agent", None)
        except Exception:
            return "failed"
        if not isinstance(health, Mapping) or health.get("healthy") is not True or not isinstance(health.get("version"), str):
            return "unsupported"
        if not isinstance(agents, list) or not any(isinstance(item, Mapping) and item.get("name") == self.agent_id for item in agents):
            return "unsupported"
        return "supported"

    def request_wake(self, session_id: str) -> str:
        """Envía sólo el prompt fijo permitido; el caller debe tener reserva E4."""
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            return "rejected"
        if self.capabilities() != "supported":
            return "unsupported"
        body = {"agent": self.agent_id, "model": {"providerID": "zai", "modelID": self.model_id},
                "parts": [{"type": "text", "text": _PROMPT}]}
        try:
            result = self._transport("POST", "/session/{}/prompt_async".format(session_id), body)
        except Exception:
            return "failed"
        return "queued" if result is None else "failed"


__all__ = ["OpenCodeWakePort"]
