"""Observador terminal GET-only para el API público local de OpenCode."""

import hashlib
import json
import re
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlparse

from .opencode_wake import (
    _PROMPT,
    _SESSION_ID,
    _VERSION,
    _body_digest,
    _message_id,
)
from .wake_reconcile import TerminalObservation


_GLM_MODEL = re.compile(r"glm-[a-z0-9.-]{2,80}")
_MESSAGE_ID = re.compile(r"msg[A-Za-z0-9_-]{0,125}")
_ACTIVE = frozenset({"busy", "retry"})
_SUPPORTED_VERSIONS = frozenset({"1.18.25"})
_MAX_PARTS = 100
_MAX_TEXT = 65536


def _evidence(**values: object) -> str:
    raw = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class OpenCodeTerminalObserver:
    """Reduce respuestas públicas a una observación saneada y ligada."""

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
                provider_version not in _SUPPORTED_VERSIONS or
                not isinstance(agent_id, str) or not _SESSION_ID.fullmatch(agent_id) or
                not isinstance(model_id, str) or not _GLM_MODEL.fullmatch(model_id) or
                not callable(transport) or
                (transport_base is not None and
                 transport_base.rstrip("/") != base_url.rstrip("/"))):
            raise ValueError("configuración de observación OpenCode no permitida")
        self.base_url = base_url.rstrip("/")
        self._provider_version = provider_version
        self._agent_id = agent_id
        self._model_id = model_id
        self._transport = transport

    def delivery_binding(self, nonce: str) -> dict:
        return {
            "provider_id": "opencode-local",
            "provider_version": self._provider_version,
            "agent_id": self._agent_id,
            "model_id": self._model_id,
            "body_digest": _body_digest(self._agent_id, self._model_id, nonce),
        }

    def _observation(self, *, target_id: str, nonce: str, outcome: str,
                     terminal: bool, text: bool = False,
                     tools: bool = False, reason: str) -> TerminalObservation:
        message_id = _message_id(nonce)
        return TerminalObservation(
            target_id=target_id,
            body_digest=_body_digest(self._agent_id, self._model_id, nonce),
            outcome=outcome,
            terminal=terminal,
            has_nonempty_text=text,
            has_tool_parts=tools,
            evidence_digest=_evidence(
                message_id=message_id, outcome=outcome, reason=reason,
                terminal=terminal, text=text, tools=tools,
            ),
        )

    def _status(self, target_id: str) -> Optional[str]:
        statuses = self._transport("GET", "/session/status", None)
        if not isinstance(statuses, Mapping) or len(statuses) > 4096:
            return None
        current = statuses.get(target_id, {"type": "idle"})
        if not isinstance(current, Mapping):
            return None
        status = current.get("type")
        return status if status in {"idle", "busy", "retry"} else None

    def _valid_user(self, value: object, *, target_id: str,
                    message_id: str) -> bool:
        if not isinstance(value, Mapping):
            return False
        info = value.get("info")
        parts = value.get("parts")
        if (not isinstance(info, Mapping) or not isinstance(parts, list) or
                len(parts) > _MAX_PARTS):
            return False
        model = info.get("model")
        expected_info = (
            info.get("id") == message_id and info.get("sessionID") == target_id and
            info.get("role") == "user" and info.get("agent") == self._agent_id and
            isinstance(model, Mapping) and model.get("providerID") == "zai" and
            model.get("modelID") == self._model_id
        )
        expected_parts = (
            len(parts) == 1 and isinstance(parts[0], Mapping) and
            parts[0].get("type") == "text" and parts[0].get("text") == _PROMPT
        )
        return bool(expected_info and expected_parts)

    def observe(self, target_id: str, nonce: str) -> TerminalObservation:
        message_id = _message_id(nonce)
        if not isinstance(target_id, str) or not _SESSION_ID.fullmatch(target_id):
            raise ValueError("sesión OpenCode no permitida")
        health = self._transport("GET", "/global/health", None)
        if (not isinstance(health, Mapping) or health.get("healthy") is not True or
                health.get("version") != self._provider_version):
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, reason="health-mismatch")
        status = self._status(target_id)
        if status is None:
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, reason="status-invalid")
        user = self._transport(
            "GET", "/session/{}/message/{}".format(target_id, message_id), None)
        if user is None:
            active = status in _ACTIVE
            return self._observation(
                target_id=target_id, nonce=nonce,
                outcome="pending" if active else "ambiguous",
                terminal=not active, reason="user-missing")
        if not self._valid_user(user, target_id=target_id, message_id=message_id):
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, reason="user-binding-mismatch")

        messages = self._transport(
            "GET", "/session/{}/message?limit=100".format(target_id), None)
        if not isinstance(messages, list) or len(messages) > 100:
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, reason="messages-invalid")
        matches = []
        for item in messages:
            if not isinstance(item, Mapping):
                continue
            info = item.get("info")
            if (isinstance(info, Mapping) and info.get("role") == "assistant" and
                    info.get("parentID") == message_id):
                matches.append(item)
        if len(matches) != 1:
            active = status in _ACTIVE and len(matches) == 0
            return self._observation(
                target_id=target_id, nonce=nonce,
                outcome="pending" if active else "ambiguous",
                terminal=not active,
                reason="assistant-missing" if not matches else "assistant-duplicate")

        assistant = matches[0]
        info = assistant.get("info")
        parts = assistant.get("parts")
        if (not isinstance(info, Mapping) or not isinstance(parts, list) or
                len(parts) > _MAX_PARTS):
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, reason="assistant-invalid")
        if (not isinstance(info.get("id"), str) or
                _MESSAGE_ID.fullmatch(info.get("id")) is None or
                info.get("id") == message_id or
                info.get("sessionID") != target_id or info.get("agent") != self._agent_id or
                info.get("providerID") != "zai" or info.get("modelID") != self._model_id or
                any(not isinstance(part, Mapping) for part in parts)):
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, reason="assistant-binding-mismatch")
        if any(isinstance(part.get("text"), str) and
               len(part.get("text")) > _MAX_TEXT for part in parts):
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, reason="assistant-content-oversized")
        tools = any(part.get("type") == "tool" for part in parts)
        text = any(
            part.get("type") == "text" and isinstance(part.get("text"), str) and
            bool(part.get("text").strip()) for part in parts
        )
        time = info.get("time")
        completed_at = time.get("completed") if isinstance(time, Mapping) else None
        finished = (
            isinstance(completed_at, int) and not isinstance(completed_at, bool) and
            completed_at >= 0 and isinstance(info.get("finish"), str) and
            bool(info.get("finish"))
        )
        if info.get("error") is not None:
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="failed",
                terminal=True, text=text, tools=tools, reason="assistant-error")
        if finished and info.get("finish") == "stop":
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="completed",
                terminal=True, text=text, tools=tools, reason="assistant-finished")
        if finished:
            return self._observation(
                target_id=target_id, nonce=nonce, outcome="ambiguous",
                terminal=True, text=text, tools=tools,
                reason="assistant-nonstop-finish")
        active = status in _ACTIVE
        return self._observation(
            target_id=target_id, nonce=nonce,
            outcome="pending" if active else "ambiguous",
            terminal=not active, text=text, tools=tools,
            reason="assistant-incomplete")


__all__ = ["OpenCodeTerminalObserver"]
