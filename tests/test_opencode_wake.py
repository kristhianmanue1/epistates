import unittest

from epistates.opencode_wake import OpenCodeWakePort


def _safe_agent(**overrides):
    agent = {
        "name": "epistates-inspect",
        "mode": "primary",
        "model": {"providerID": "zai", "modelID": "glm-5.2"},
        "permission": [
            {"permission": "*", "pattern": "*", "action": "allow"},
            {"permission": "read", "pattern": "*", "action": "allow"},
            {"permission": "*", "pattern": "*", "action": "deny"},
            {"permission": "external_directory", "pattern": "*", "action": "deny"},
            {"permission": "external_directory",
             "pattern": "/Users/test/.local/share/opencode/tool-output/*",
             "action": "allow"},
        ],
    }
    agent.update(overrides)
    return agent


class OpenCodeWakePortTests(unittest.TestCase):
    def setUp(self):
        self.nonce = "a" * 32
        self.calls = []
        def transport(method, path, body):
            self.calls.append((method, path, body))
            if path == "/global/health": return {"healthy": True, "version": "1.18.25"}
            if path == "/agent": return [_safe_agent()]
            if path.endswith("/prompt_async"): return None
            raise AssertionError(path)
        self.port = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.25",
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
        self.assertEqual(binding["provider_version"], "1.18.25")
        self.assertRegex(binding["body_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(
            binding["body_digest"],
            self.port.delivery_binding("b" * 32)["body_digest"],
        )

    def test_unhealthy_or_missing_agent_never_posts(self):
        port = OpenCodeWakePort(
            "http://localhost:4096", provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=lambda method, path, body: {"healthy": False, "version": "1"}
            if path == "/global/health" else [],
        )
        self.assertEqual(port.request_wake("ses-one", self.nonce), "unsupported")

    def test_provider_version_mismatch_never_posts(self):
        self.calls.clear()
        self.assertEqual(self.port.capabilities(), "supported")
        def transport(method, path, body):
            self.calls.append((method, path, body))
            if path == "/global/health":
                return {"healthy": True, "version": "1.18.24"}
            return [_safe_agent()]
        mismatch = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=transport,
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
                "https://example.com", provider_version="1.18.25",
                agent_id="epistates-inspect", model_id="glm-5.2",
                transport=lambda *_: None,
            )
        with self.assertRaises(ValueError):
            OpenCodeWakePort(
                "http://token@localhost:4096", provider_version="1.18.25",
                agent_id="epistates-inspect", model_id="glm-5.2",
                transport=lambda *_: None,
            )
        self.assertEqual(
            self.port.request_wake("bad space", self.nonce), "rejected")
        self.assertEqual(self.port.request_wake("ses-one", "bad"), "rejected")
        port = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=lambda *_: (_ for _ in ()).throw(OSError()),
        )
        self.assertEqual(port.request_wake("ses-one", self.nonce), "unsupported")

    def test_only_exact_provider_version_is_constructible(self):
        with self.assertRaises(ValueError):
            OpenCodeWakePort(
                "http://127.0.0.1:4096", provider_version="1.18.24",
                agent_id="epistates-inspect", model_id="glm-5.2",
                transport=lambda *_: None,
            )

    def test_identity_mode_model_and_uniqueness_fail_closed(self):
        variants = [
            [],
            [_safe_agent(), _safe_agent()],
            [_safe_agent(mode="all")],
            [_safe_agent(model={"providerID": "other", "modelID": "glm-5.2"})],
            [_safe_agent(model={"providerID": "zai", "modelID": "glm-other"})],
            [_safe_agent(name="other")],
        ]
        for agents in variants:
            with self.subTest(agents=agents):
                port = OpenCodeWakePort(
                    "http://127.0.0.1:4096", provider_version="1.18.25",
                    agent_id="epistates-inspect", model_id="glm-5.2",
                    transport=lambda method, path, body, agents=agents:
                    {"healthy": True, "version": "1.18.25"}
                    if path == "/global/health" else agents,
                )
                self.assertEqual(port.capabilities(), "unsupported")

    def test_ordered_rules_accept_only_bounded_truncation_exception(self):
        safe_without_exception = _safe_agent(permission=[
            {"permission": "*", "pattern": "*", "action": "deny"},
            {"permission": "external_directory", "pattern": "*", "action": "deny"},
        ])
        safe_with_hostile_defaults = _safe_agent()
        for agent in (safe_without_exception, safe_with_hostile_defaults):
            with self.subTest(agent=agent):
                port = OpenCodeWakePort(
                    "http://127.0.0.1:4096", provider_version="1.18.25",
                    agent_id="epistates-inspect", model_id="glm-5.2",
                    transport=lambda method, path, body, agent=agent:
                    {"healthy": True, "version": "1.18.25"}
                    if path == "/global/health" else [agent],
                )
                self.assertEqual(port.capabilities(), "supported")

    def test_late_reopen_or_unsafe_external_rule_fails_closed(self):
        bad_tails = [
            [],
            [{"permission": "read", "pattern": "*", "action": "allow"}],
            [{"permission": "*", "pattern": "*", "action": "ask"}],
            [{"permission": "external_directory", "pattern": "*", "action": "allow"}],
            [
                {"permission": "external_directory", "pattern": "*", "action": "deny"},
                {"permission": "external_directory", "pattern": "relative/opencode/tool-output/*", "action": "allow"},
            ],
            [
                {"permission": "external_directory", "pattern": "*", "action": "deny"},
                {"permission": "external_directory", "pattern": "/safe/../opencode/tool-output/*", "action": "allow"},
            ],
            [
                {"permission": "external_directory", "pattern": "*", "action": "deny"},
                {"permission": "external_directory", "pattern": "/safe/opencode/other/*", "action": "allow"},
            ],
        ]
        for tail in bad_tails:
            rules = ([{"permission": "*", "pattern": "*", "action": "allow"}]
                     if not tail else
                     [{"permission": "*", "pattern": "*", "action": "deny"}] + tail)
            agent = _safe_agent(permission=rules)
            with self.subTest(tail=tail):
                port = OpenCodeWakePort(
                    "http://127.0.0.1:4096", provider_version="1.18.25",
                    agent_id="epistates-inspect", model_id="glm-5.2",
                    transport=lambda method, path, body, agent=agent:
                    {"healthy": True, "version": "1.18.25"}
                    if path == "/global/health" else [agent],
                )
                self.assertEqual(port.capabilities(), "unsupported")

    def test_malformed_or_oversized_rules_fail_closed(self):
        bad_permissions = [
            None,
            {},
            [{"permission": "*", "pattern": "*"}],
            [{"permission": "bad\n", "pattern": "*", "action": "deny"}],
            [{"permission": "*", "pattern": "bad\n", "action": "deny"}],
            [{"permission": "*", "pattern": "*", "action": "deny"}] * 257,
        ]
        for permissions in bad_permissions:
            agent = _safe_agent(permission=permissions)
            with self.subTest(permissions=permissions):
                port = OpenCodeWakePort(
                    "http://127.0.0.1:4096", provider_version="1.18.25",
                    agent_id="epistates-inspect", model_id="glm-5.2",
                    transport=lambda method, path, body, agent=agent:
                    {"healthy": True, "version": "1.18.25"}
                    if path == "/global/health" else [agent],
                )
                self.assertEqual(port.capabilities(), "unsupported")

    def test_unsafe_permission_tail_never_posts(self):
        calls = []
        agent = _safe_agent(permission=[
            {"permission": "*", "pattern": "*", "action": "deny"},
            {"permission": "read", "pattern": "*", "action": "allow"},
        ])

        def transport(method, path, body):
            calls.append((method, path, body))
            if path == "/global/health":
                return {"healthy": True, "version": "1.18.25"}
            if path == "/agent":
                return [agent]
            raise AssertionError("POST no permitido")

        port = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=transport,
        )
        self.assertEqual(port.request_wake("ses-one", self.nonce), "unsupported")
        self.assertFalse(any(method == "POST" for method, _, _ in calls))
