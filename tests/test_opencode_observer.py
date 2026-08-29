import ast
import inspect
import tempfile
import unittest
from pathlib import Path

from epistates.delivery_ledger import DeliveryLedgerStore
import epistates.opencode_observer as opencode_observer
from epistates.opencode_observer import OpenCodeTerminalObserver
from epistates.opencode_wake import OpenCodeWakePort
from epistates.wake_reconcile import WakeTerminalReconciler


class FakeTransport:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value


class OpenCodeTerminalObserverTests(unittest.TestCase):
    def setUp(self):
        self.nonce = "a" * 32
        self.message_id = "msg_e4_" + self.nonce
        self.target = "ses-one"
        self.user = {
            "info": {
                "id": self.message_id,
                "sessionID": self.target,
                "role": "user",
                "agent": "epistates-inspect",
                "model": {"providerID": "zai", "modelID": "glm-5.2"},
            },
            "parts": [{
                "type": "text",
                "text": "Controller requested a read-only status check. "
                        "Do not execute commands or modify files.",
            }],
        }
        self.assistant = {
            "info": {
                "id": "msg-assistant",
                "sessionID": self.target,
                "parentID": self.message_id,
                "role": "assistant",
                "agent": "epistates-inspect",
                "providerID": "zai",
                "modelID": "glm-5.2",
                "time": {"created": 1, "completed": 2},
                "finish": "stop",
            },
            "parts": [{"type": "text", "text": "status complete"}],
        }

    def responses(self, *, status=None, user="default", messages="default"):
        return {
            "/global/health": {"healthy": True, "version": "1.18.25"},
            "/session/status": {} if status is None else status,
            f"/session/{self.target}/message/{self.message_id}":
                self.user if user == "default" else user,
            f"/session/{self.target}/message?limit=100":
                [self.user, self.assistant] if messages == "default" else messages,
        }

    def observer(self, responses=None):
        transport = FakeTransport(responses or self.responses())
        observer = OpenCodeTerminalObserver(
            "http://127.0.0.1:4096", provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=transport,
        )
        return observer, transport

    def test_binding_equals_wake_port_for_same_nonce(self):
        observer, _ = self.observer()
        wake = OpenCodeWakePort(
            "http://localhost:4096", provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=lambda *_: None,
        )
        self.assertEqual(
            observer.delivery_binding(self.nonce),
            wake.delivery_binding(self.nonce),
        )
        self.assertNotEqual(
            observer.delivery_binding(self.nonce)["body_digest"],
            observer.delivery_binding("b" * 32)["body_digest"],
        )

    def test_only_audited_version_and_credential_free_local_url_are_allowed(self):
        for url, version in (("http://localhost:4096", "1.18.24"),
                             ("http://token@localhost:4096", "1.18.25")):
            with self.subTest(url=url, version=version), self.assertRaises(ValueError):
                OpenCodeTerminalObserver(
                    url, provider_version=version,
                    agent_id="epistates-inspect", model_id="glm-5.2",
                    transport=lambda *_: None,
                )

    def test_completed_is_sanitized_and_uses_get_only(self):
        observer, transport = self.observer()
        result = observer.observe(self.target, self.nonce)
        self.assertEqual(result.outcome, "completed")
        self.assertTrue(result.terminal)
        self.assertTrue(result.has_nonempty_text)
        self.assertFalse(result.has_tool_parts)
        self.assertRegex(result.evidence_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("status complete", repr(result))
        self.assertTrue(all(method == "GET" and body is None
                            for method, _, body in transport.calls))

    def test_missing_user_is_pending_only_while_status_is_active(self):
        for status, expected, terminal in (
                ({self.target: {"type": "busy"}}, "pending", False),
                ({self.target: {"type": "retry"}}, "pending", False),
                ({}, "ambiguous", True)):
            with self.subTest(status=status, expected=expected):
                observer, _ = self.observer(self.responses(
                    status=status, user=None, messages=[]))
                result = observer.observe(self.target, self.nonce)
                self.assertEqual(result.outcome, expected)
                self.assertEqual(result.terminal, terminal)

    def test_error_tools_and_empty_text_remain_distinguishable(self):
        error = dict(self.assistant)
        error["info"] = dict(self.assistant["info"], error={"name": "APIError"})
        tools = dict(self.assistant)
        tools["parts"] = [{"type": "tool", "state": {"status": "completed"}}]
        empty = dict(self.assistant)
        empty["parts"] = [{"type": "text", "text": "   "}]
        for assistant, outcome, has_tools, has_text in (
                (error, "failed", False, True),
                (tools, "completed", True, False),
                (empty, "completed", False, False)):
            with self.subTest(outcome=outcome, tools=has_tools, text=has_text):
                observer, _ = self.observer(self.responses(
                    messages=[self.user, assistant]))
                result = observer.observe(self.target, self.nonce)
                self.assertEqual(result.outcome, outcome)
                self.assertEqual(result.has_tool_parts, has_tools)
                self.assertEqual(result.has_nonempty_text, has_text)

    def test_cross_binding_duplicate_and_hostile_shapes_are_ambiguous(self):
        crossed_user = dict(self.user)
        crossed_user["info"] = dict(self.user["info"], id="msg_other")
        crossed_assistant = dict(self.assistant)
        crossed_assistant["info"] = dict(
            self.assistant["info"], modelID="glm-other")
        cases = (
            self.responses(user=crossed_user),
            self.responses(messages=[self.user, crossed_assistant]),
            self.responses(messages=[self.user, self.assistant, self.assistant]),
            self.responses(messages={"not": "a list"}),
            self.responses(status={self.target: {"type": "unknown"}}),
        )
        for index, responses in enumerate(cases):
            with self.subTest(index=index):
                observer, _ = self.observer(responses)
                result = observer.observe(self.target, self.nonce)
                self.assertEqual(result.outcome, "ambiguous")
                self.assertTrue(result.terminal)

    def test_incomplete_assistant_pending_only_while_active(self):
        incomplete = dict(self.assistant)
        incomplete["info"] = dict(self.assistant["info"])
        incomplete["info"].pop("finish")
        incomplete["info"]["time"] = {"created": 1}
        for status, expected in (({self.target: {"type": "busy"}}, "pending"),
                                 ({}, "ambiguous")):
            with self.subTest(status=status):
                observer, _ = self.observer(self.responses(
                    status=status, messages=[self.user, incomplete]))
                self.assertEqual(
                    observer.observe(self.target, self.nonce).outcome, expected)

    def test_nonstop_finish_boolean_timestamp_and_oversized_text_are_ambiguous(self):
        length = dict(self.assistant)
        length["info"] = dict(self.assistant["info"], finish="length")
        boolean_time = dict(self.assistant)
        boolean_time["info"] = dict(
            self.assistant["info"], time={"created": 1, "completed": True})
        oversized = dict(self.assistant)
        oversized["parts"] = [{"type": "text", "text": "x" * 65537}]
        for assistant in (length, boolean_time, oversized):
            with self.subTest(assistant=assistant["info"].get("finish")):
                observer, _ = self.observer(self.responses(
                    messages=[self.user, assistant]))
                result = observer.observe(self.target, self.nonce)
                self.assertEqual(result.outcome, "ambiguous")
                self.assertTrue(result.terminal)

    def test_reconciler_integration_completes_exact_bound_attempt(self):
        observer, _ = self.observer()
        with tempfile.TemporaryDirectory() as tmp:
            store = DeliveryLedgerStore(Path(tmp) / "observer.sqlite")
            binding = observer.delivery_binding(self.nonce)
            self.assertEqual(store.create_reserved(
                nonce=self.nonce, receipt_digest="sha256:" + "b" * 64,
                target_id=self.target, observed_at="2026-08-28T20:00:00Z",
                **binding,
            ), "reserved")
            self.assertEqual(store.transition(
                nonce=self.nonce, expected_state="reserved", new_state="submitting",
                observed_at="2026-08-28T20:00:01Z",
            ), "updated")
            self.assertEqual(store.transition(
                nonce=self.nonce, expected_state="submitting", new_state="submitted",
                observed_at="2026-08-28T20:00:02Z",
                result_class="provider-queued",
                evidence_digest="sha256:" + "c" * 64,
            ), "updated")
            self.assertEqual(WakeTerminalReconciler(store, observer).reconcile(
                nonce=self.nonce, observed_at="2026-08-28T20:00:03Z",
            ), "completed")

    def test_module_has_no_concrete_network_or_process_client(self):
        tree = ast.parse(inspect.getsource(opencode_observer))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint({
            "httpx", "requests", "socket", "subprocess",
        }))


if __name__ == "__main__":
    unittest.main()
