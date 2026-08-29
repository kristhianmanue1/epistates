"""Transportes HTTP loopback de mínimo privilegio para OpenCode E4."""

import base64
import http.client
import json
import math
import re
from typing import Any, Callable, Mapping, Optional

from .opencode_wake import _PROMPT


_USERNAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SESSION_ID = r"[A-Za-z0-9_-]{3,128}"
_MESSAGE_ID = r"msg_e4_[0-9a-f]{32}"
_E4_MESSAGE_ID = re.compile(r"msg_e4_[0-9a-f]{32}")
_AGENT_ID = re.compile(r"[A-Za-z0-9_-]{3,128}")
_GLM_MODEL = re.compile(r"glm-[a-z0-9.-]{2,80}")
_READ_PATHS = (
    re.compile(r"/global/health"),
    re.compile(r"/session/status"),
    re.compile(rf"/session/{_SESSION_ID}/message/{_MESSAGE_ID}"),
    re.compile(rf"/session/{_SESSION_ID}/message\?limit=100"),
)
_SUBMISSION_GET_PATHS = (
    re.compile(r"/global/health"),
    re.compile(r"/agent"),
)
_SUBMISSION_POST = re.compile(rf"/session/{_SESSION_ID}/prompt_async")
_MAX_REQUEST_BYTES = 4096
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 100000


class OpenCodeTransportError(RuntimeError):
    """Fallo saneado: nunca incluye URL completa, body, respuesta o secreto."""

    def __init__(self):
        super().__init__("OpenCode HTTP transport failed")


def _matches(path: str, patterns: tuple) -> bool:
    return any(pattern.fullmatch(path) is not None for pattern in patterns)


def _reject_constant(_: str):
    raise ValueError("constante JSON no permitida")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("clave JSON duplicada")
        result[key] = value
    return result


def _bounded_json(raw: bytes) -> Any:
    decoded = raw.decode("utf-8", errors="strict")
    value = json.loads(
        decoded, object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    stack = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise ValueError("JSON fuera de límites")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif not isinstance(current, (str, int, float, bool, type(None))):
            raise ValueError("tipo JSON no permitido")
        elif isinstance(current, float) and not math.isfinite(current):
            raise ValueError("número JSON no finito")
    return value


class _BaseOpenCodeTransport:
    def __init__(self, *, port: int, username: str, password: str,
                 timeout_seconds: float = 2.0,
                 max_response_bytes: int = 1048576,
                 connection_factory: Callable[..., Any] = http.client.HTTPConnection):
        if (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535 or
                not isinstance(username, str) or _USERNAME.fullmatch(username) is None or
                not isinstance(password, str) or not 1 <= len(password) <= 1024 or
                "\r" in password or "\n" in password or
                not isinstance(timeout_seconds, (int, float)) or
                isinstance(timeout_seconds, bool) or
                not math.isfinite(float(timeout_seconds)) or
                not 0.1 <= float(timeout_seconds) <= 10.0 or
                not isinstance(max_response_bytes, int) or
                isinstance(max_response_bytes, bool) or
                not 1024 <= max_response_bytes <= 2097152 or
                not callable(connection_factory)):
            raise ValueError("configuración HTTP OpenCode no permitida")
        self._port = port
        self._username = username
        self._password = password
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._connection_factory = connection_factory

    @property
    def base_url(self) -> str:
        return "http://127.0.0.1:{}".format(self._port)

    def _allowed(self, method: str, path: str, body: object) -> bool:
        raise NotImplementedError

    def _encode_body(self, method: str, body: object) -> Optional[bytes]:
        if method == "GET":
            return None
        raw = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        if len(raw) > _MAX_REQUEST_BYTES:
            raise OpenCodeTransportError()
        return raw

    def __call__(self, method: str, path: str,
                 body: Optional[Mapping[str, Any]]) -> Any:
        if not isinstance(method, str) or not isinstance(path, str):
            raise OpenCodeTransportError()
        connection = None
        try:
            if not self._allowed(method, path, body):
                raise OpenCodeTransportError()
            payload = self._encode_body(method, body)
            token = base64.b64encode(
                (self._username + ":" + self._password).encode("utf-8")
            ).decode("ascii")
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Authorization": "Basic " + token,
                "Connection": "close",
            }
            if payload is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(payload))
            connection = self._connection_factory(
                "127.0.0.1", self._port, timeout=self._timeout_seconds)
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            expected = 204 if method == "POST" else 200
            if response.status != expected:
                raise OpenCodeTransportError()
            encoding = response.getheader("Content-Encoding")
            if encoding not in {None, "", "identity"}:
                raise OpenCodeTransportError()
            length = response.getheader("Content-Length")
            if length is not None:
                if not length.isdigit() or int(length) > self._max_response_bytes:
                    raise OpenCodeTransportError()
            raw = response.read(self._max_response_bytes + 1)
            if len(raw) > self._max_response_bytes:
                raise OpenCodeTransportError()
            if method == "POST":
                if raw:
                    raise OpenCodeTransportError()
                return None
            content_type = response.getheader("Content-Type")
            if (not isinstance(content_type, str) or
                    content_type.split(";", 1)[0].strip().lower() != "application/json"):
                raise OpenCodeTransportError()
            return _bounded_json(raw)
        except OpenCodeTransportError:
            raise
        except Exception:
            raise OpenCodeTransportError() from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


class OpenCodeReadTransport(_BaseOpenCodeTransport):
    """Sólo permite los cuatro GET usados por la reconciliación terminal."""

    def _allowed(self, method: str, path: str, body: object) -> bool:
        return method == "GET" and body is None and _matches(path, _READ_PATHS)


class OpenCodeSubmissionTransport(_BaseOpenCodeTransport):
    """Permite health/agent GET y un único shape POST prompt_async."""

    @staticmethod
    def _valid_submission(body: object) -> bool:
        if not isinstance(body, Mapping) or set(body) != {
                "messageID", "agent", "model", "parts"}:
            return False
        model = body.get("model")
        parts = body.get("parts")
        return bool(
            isinstance(body.get("messageID"), str) and
            _E4_MESSAGE_ID.fullmatch(body.get("messageID")) is not None and
            isinstance(body.get("agent"), str) and
            _AGENT_ID.fullmatch(body.get("agent")) is not None and
            isinstance(model, Mapping) and set(model) == {"providerID", "modelID"} and
            model.get("providerID") == "zai" and
            isinstance(model.get("modelID"), str) and
            _GLM_MODEL.fullmatch(model.get("modelID")) is not None and
            isinstance(parts, list) and len(parts) == 1 and
            isinstance(parts[0], Mapping) and set(parts[0]) == {"type", "text"} and
            parts[0].get("type") == "text" and parts[0].get("text") == _PROMPT
        )

    def _allowed(self, method: str, path: str, body: object) -> bool:
        if method == "GET":
            return body is None and _matches(path, _SUBMISSION_GET_PATHS)
        return bool(
            method == "POST" and _SUBMISSION_POST.fullmatch(path) is not None and
            self._valid_submission(body)
        )


__all__ = [
    "OpenCodeReadTransport",
    "OpenCodeSubmissionTransport",
    "OpenCodeTransportError",
]
