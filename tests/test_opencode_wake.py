import unittest

from epistates.opencode_wake import OpenCodeWakePort


class OpenCodeWakePortTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def transport(method, path, body):
            self.calls.append((method, path, body))
            if path == "/global/health": return {"healthy": True, "version": "1.18.23"}
            if path == "/agent": return [{"name": "epistates-inspect"}]
            if path.endswith("/prompt_async"): return None
            raise AssertionError(path)
        self.port = OpenCodeWakePort("http://127.0.0.1:4096", agent_id="epistates-inspect", model_id="glm-5.2", transport=transport)

    def test_allowlist_queues_fixed_read_only_prompt(self):
        self.assertEqual(self.port.request_wake("ses-one"), "queued")
        method, path, body = self.calls[-1]
        self.assertEqual((method, path), ("POST", "/session/ses-one/prompt_async"))
        self.assertEqual(body["model"], {"providerID": "zai", "modelID": "glm-5.2"})
        self.assertIn("Do not execute", body["parts"][0]["text"])

    def test_unhealthy_or_missing_agent_never_posts(self):
        port = OpenCodeWakePort("http://localhost:4096", agent_id="epistates-inspect", model_id="glm-5.2", transport=lambda method, path, body: {"healthy": False, "version": "1"} if path == "/global/health" else [])
        self.assertEqual(port.request_wake("ses-one"), "unsupported")

    def test_invalid_url_session_and_network_error_fail_closed(self):
        with self.assertRaises(ValueError):
            OpenCodeWakePort("https://example.com", agent_id="epistates-inspect", model_id="glm-5.2", transport=lambda *_: None)
        self.assertEqual(self.port.request_wake("bad space"), "rejected")
        port = OpenCodeWakePort("http://127.0.0.1:4096", agent_id="epistates-inspect", model_id="glm-5.2", transport=lambda *_: (_ for _ in ()).throw(OSError()))
        self.assertEqual(port.request_wake("ses-one"), "unsupported")
