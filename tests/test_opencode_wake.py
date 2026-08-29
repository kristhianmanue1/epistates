import unittest

from epistates.opencode_wake import OpenCodeWakePort


class OpenCodeWakePortTests(unittest.TestCase):
    def setUp(self):
        self.nonce = "a" * 32
        self.calls = []
        def transport(method, path, body):
            self.calls.append((method, path, body))
            if path == "/global/health": return {"healthy": True, "version": "1.18.23"}
            if path == "/agent": return [{"name": "epistates-inspect"}]
            if path.endswith("/prompt_async"): return None
            raise AssertionError(path)
        self.port = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.23",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=transport,
        )

    def test_allowlist_queues_fixed_read_only_prompt(self):
        self.assertEqual(self.port.request_wake("ses-one", self.nonce), "queued")
        method, path, body = self.calls[-1]
        self.assertEqual((method, path), ("POST", "/session/ses-one/prompt_async"))
        self.assertEqual(body["messageID"], "msg_e4_" + self.nonce)
        self.assertEqual(body["model"], {"providerID": "zai", "modelID": "glm-5.2"})
        self.assertIn("Do not execute", body["parts"][0]["text"])
        binding = self.port.delivery_binding(self.nonce)
        self.assertEqual(binding["provider_id"], "opencode-local")
        self.assertEqual(binding["provider_version"], "1.18.23")
        self.assertRegex(binding["body_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(
            binding["body_digest"],
            self.port.delivery_binding("b" * 32)["body_digest"],
        )

    def test_unhealthy_or_missing_agent_never_posts(self):
        port = OpenCodeWakePort(
            "http://localhost:4096", provider_version="1.18.23",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=lambda method, path, body: {"healthy": False, "version": "1"}
            if path == "/global/health" else [],
        )
        self.assertEqual(port.request_wake("ses-one", self.nonce), "unsupported")

    def test_provider_version_mismatch_never_posts(self):
        self.calls.clear()
        self.assertEqual(self.port.capabilities(), "supported")
        mismatch = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.24",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=self.port._transport,
        )
        self.assertEqual(mismatch.request_wake("ses-one", self.nonce), "unsupported")
        self.assertFalse(any(method == "POST" for method, _, _ in self.calls))

    def test_binding_configuration_is_read_only(self):
        with self.assertRaises(AttributeError):
            self.port.model_id = "glm-other"
        with self.assertRaises(AttributeError):
            self.port.provider_version = "1.18.24"
        self.assertEqual(
            self.port.delivery_binding(self.nonce)["model_id"], "glm-5.2")

    def test_invalid_url_session_and_network_error_fail_closed(self):
        with self.assertRaises(ValueError):
            OpenCodeWakePort(
                "https://example.com", provider_version="1.18.23",
                agent_id="epistates-inspect", model_id="glm-5.2",
                transport=lambda *_: None,
            )
        with self.assertRaises(ValueError):
            OpenCodeWakePort(
                "http://token@localhost:4096", provider_version="1.18.23",
                agent_id="epistates-inspect", model_id="glm-5.2",
                transport=lambda *_: None,
            )
        self.assertEqual(
            self.port.request_wake("bad space", self.nonce), "rejected")
        self.assertEqual(self.port.request_wake("ses-one", "bad"), "rejected")
        port = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.23",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=lambda *_: (_ for _ in ()).throw(OSError()),
        )
        self.assertEqual(port.request_wake("ses-one", self.nonce), "unsupported")
