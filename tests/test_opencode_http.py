import base64
import json
import unittest
from collections.abc import Mapping

from epistates.opencode_http import (
    OpenCodeReadTransport,
    OpenCodeSubmissionTransport,
    OpenCodeTransportError,
)
from epistates.opencode_observer import OpenCodeTerminalObserver
from epistates.opencode_wake import OpenCodeWakePort


class FakeResponse:
    def __init__(self, value=None, *, status=200, raw=None, headers=None):
        self.status = status
        self.raw = (json.dumps(value).encode("utf-8") if raw is None else raw)
        self.headers = ({"Content-Type": "application/json"}
                        if headers is None else dict(headers))

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        return self.raw[:amount]


class FakeConnection:
    def __init__(self, factory):
        self.factory = factory
        self.request_values = None
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.request_values = (method, path, body, dict(headers or {}))
        self.factory.requests.append(self.request_values)

    def getresponse(self):
        method, path, _, _ = self.request_values
        value = self.factory.routes[(method, path)]
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


class FakeConnectionFactory:
    def __init__(self, routes):
        self.routes = dict(routes)
        self.requests = []
        self.connections = []
        self.opens = []

    def __call__(self, host, port, *, timeout):
        self.opens.append((host, port, timeout))
        connection = FakeConnection(self)
        self.connections.append(connection)
        return connection


class OpenCodeHTTPTransportTests(unittest.TestCase):
    def read_transport(self, routes, **overrides):
        factory = FakeConnectionFactory(routes)
        values = dict(
            port=4096, username="opencode", password="secret-value",
            connection_factory=factory,
        )
        values.update(overrides)
        return OpenCodeReadTransport(**values), factory

    def submission_transport(self, routes, **overrides):
        factory = FakeConnectionFactory(routes)
        values = dict(
            port=4096, username="opencode", password="secret-value",
            connection_factory=factory,
        )
        values.update(overrides)
        return OpenCodeSubmissionTransport(**values), factory

    def test_read_transport_uses_numeric_loopback_auth_and_closes(self):
        transport, factory = self.read_transport({
            ("GET", "/global/health"):
                FakeResponse({"healthy": True, "version": "1.18.25"}),
        })
        self.assertEqual(transport.base_url, "http://127.0.0.1:4096")
        self.assertEqual(
            transport("GET", "/global/health", None),
            {"healthy": True, "version": "1.18.25"},
        )
        self.assertEqual(factory.opens, [("127.0.0.1", 4096, 2.0)])
        method, path, body, headers = factory.requests[0]
        self.assertEqual((method, path, body), ("GET", "/global/health", None))
        expected = base64.b64encode(b"opencode:secret-value").decode("ascii")
        self.assertEqual(headers["Authorization"], "Basic " + expected)
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertTrue(factory.connections[0].closed)

    def test_read_transport_rejects_methods_paths_and_bodies_before_connect(self):
        transport, factory = self.read_transport({})
        for values in (
                ("POST", "/global/health", {}),
                ("GET", "/event", None),
                ("GET", "/session/ses-one/message/msg_other", None),
                ("GET", "/session/ses-one/message?limit=101", None),
                ("GET", "/session/status", {}),
                ("get", "/global/health", None)):
            with self.subTest(values=values), self.assertRaises(OpenCodeTransportError):
                transport(*values)
        self.assertEqual(factory.opens, [])

    def test_hostile_mapping_is_sanitized_before_connect(self):
        class HostileMapping(Mapping):
            def __getitem__(self, key):
                raise RuntimeError("secret mapping failure")

            def __iter__(self):
                raise RuntimeError("secret mapping failure")

            def __len__(self):
                raise RuntimeError("secret mapping failure")

        transport, factory = self.submission_transport({})
        with self.assertRaises(OpenCodeTransportError) as caught:
            transport("POST", "/session/ses-one/prompt_async", HostileMapping())
        self.assertNotIn("secret mapping failure", str(caught.exception))
        self.assertEqual(factory.opens, [])

    def test_submission_transport_has_distinct_minimal_allowlist(self):
        nonce = "a" * 32
        routes = {
            ("GET", "/global/health"):
                FakeResponse({"healthy": True, "version": "1.18.25"}),
            ("GET", "/agent"):
                FakeResponse([{"name": "epistates-inspect"}]),
            ("POST", "/session/ses-one/prompt_async"):
                FakeResponse(status=204, raw=b"", headers={}),
        }
        transport, factory = self.submission_transport(routes)
        port = OpenCodeWakePort(
            transport.base_url, provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=transport,
        )
        self.assertEqual(port.request_wake("ses-one", nonce), "queued")
        self.assertEqual([method for method, _, _, _ in factory.requests],
                         ["GET", "GET", "POST"])
        post = factory.requests[-1]
        self.assertEqual(json.loads(post[2])["messageID"], "msg_e4_" + nonce)
        with self.assertRaises(OpenCodeTransportError):
            transport("GET", "/session/status", None)

    def test_submission_rejects_noncanonical_body_before_connect(self):
        transport, factory = self.submission_transport({})
        valid = {
            "messageID": "msg_e4_" + "a" * 32,
            "agent": "epistates-inspect",
            "model": {"providerID": "zai", "modelID": "glm-5.2"},
            "parts": [{
                "type": "text",
                "text": "Controller requested a read-only status check. "
                        "Do not execute commands or modify files.",
            }],
        }
        for body in (
                dict(valid, extra=True),
                dict(valid, messageID="msg_other"),
                dict(valid, agent="bad space"),
                dict(valid, parts=[{"type": "text", "text": "other"}])):
            with self.subTest(body=body), self.assertRaises(OpenCodeTransportError):
                transport("POST", "/session/ses-one/prompt_async", body)
        self.assertEqual(factory.opens, [])

    def test_response_status_encoding_type_and_size_fail_closed(self):
        cases = (
            FakeResponse({}, status=302),
            FakeResponse({}, headers={"Content-Type": "application/json",
                                      "Content-Encoding": "gzip"}),
            FakeResponse({}, headers={"Content-Type": "text/plain"}),
            FakeResponse(raw=b"{" + b"x" * 1024,
                         headers={"Content-Type": "application/json"}),
            FakeResponse({}, headers={"Content-Type": "application/json",
                                      "Content-Length": "1025"}),
        )
        for index, response in enumerate(cases):
            with self.subTest(index=index):
                transport, factory = self.read_transport(
                    {("GET", "/global/health"): response},
                    max_response_bytes=1024,
                )
                with self.assertRaises(OpenCodeTransportError):
                    transport("GET", "/global/health", None)
                self.assertTrue(factory.connections[0].closed)

    def test_json_duplicates_nonfinite_depth_and_utf8_fail_closed(self):
        deep = ("[" * 34 + "0" + "]" * 34).encode("ascii")
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', deep, b'"\xff"'):
            with self.subTest(raw=raw[:20]):
                transport, _ = self.read_transport({
                    ("GET", "/global/health"): FakeResponse(raw=raw),
                })
                with self.assertRaises(OpenCodeTransportError):
                    transport("GET", "/global/health", None)

    def test_errors_and_repr_never_expose_password_or_response(self):
        transport, _ = self.read_transport({
            ("GET", "/global/health"): OSError("remote secret response"),
        })
        with self.assertRaises(OpenCodeTransportError) as caught:
            transport("GET", "/global/health", None)
        combined = repr(transport) + str(caught.exception)
        self.assertNotIn("secret-value", combined)
        self.assertNotIn("remote secret response", combined)

    def test_invalid_configuration_is_rejected(self):
        factory = FakeConnectionFactory({})
        cases = (
            dict(port=0, username="opencode", password="x"),
            dict(port=True, username="opencode", password="x"),
            dict(port=4096, username="bad user", password="x"),
            dict(port=4096, username="opencode", password=""),
            dict(port=4096, username="opencode", password="x\nheader"),
            dict(port=4096, username="opencode", password="x", timeout_seconds=60),
            dict(port=4096, username="opencode", password="x", max_response_bytes=100),
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                OpenCodeReadTransport(connection_factory=factory, **values)

    def test_adapter_rejects_transport_base_url_mismatch(self):
        transport, _ = self.read_transport({})
        with self.assertRaises(ValueError):
            OpenCodeTerminalObserver(
                "http://localhost:4096", provider_version="1.18.25",
                agent_id="epistates-inspect", model_id="glm-5.2",
                transport=transport,
            )

    def test_read_transport_integrates_with_terminal_observer(self):
        nonce = "a" * 32
        message_id = "msg_e4_" + nonce
        user = {
            "info": {
                "id": message_id, "sessionID": "ses-one", "role": "user",
                "agent": "epistates-inspect",
                "model": {"providerID": "zai", "modelID": "glm-5.2"},
            },
            "parts": [{
                "type": "text",
                "text": "Controller requested a read-only status check. "
                        "Do not execute commands or modify files.",
            }],
        }
        assistant = {
            "info": {
                "id": "msg_assistant", "sessionID": "ses-one",
                "parentID": message_id, "role": "assistant",
                "agent": "epistates-inspect", "providerID": "zai",
                "modelID": "glm-5.2", "time": {"completed": 2},
                "finish": "stop",
            },
            "parts": [{"type": "text", "text": "done"}],
        }
        routes = {
            ("GET", "/global/health"):
                FakeResponse({"healthy": True, "version": "1.18.25"}),
            ("GET", "/session/status"): FakeResponse({}),
            ("GET", f"/session/ses-one/message/{message_id}"):
                FakeResponse(user),
            ("GET", "/session/ses-one/message?limit=100"):
                FakeResponse([user, assistant]),
        }
        transport, factory = self.read_transport(routes)
        observer = OpenCodeTerminalObserver(
            transport.base_url, provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=transport,
        )
        result = observer.observe("ses-one", nonce)
        self.assertEqual(result.outcome, "completed")
        self.assertTrue(all(request[0] == "GET" for request in factory.requests))


if __name__ == "__main__":
    unittest.main()
