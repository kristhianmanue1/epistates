import ast
import hashlib
import inspect
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from epistates import onboarding
from epistates.contracts import validate_task_card
from epistates.discovery import build_discovery_document
from epistates.onboarding import OnboardingResourceError


SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def _stack(patches):
    stack = ExitStack()
    for patcher in patches:
        stack.enter_context(patcher)
    return stack


class InventoryTests(unittest.TestCase):
    def test_inventory_lists_three_resources(self):
        ids = {r["resource_id"] for r in onboarding.onboarding_inventory()}
        self.assertEqual(ids, {"agent-guide", "minimal-task-card", "walkthrough"})

    def test_every_resource_disclaims_instruction_and_grant(self):
        for r in onboarding.onboarding_inventory():
            self.assertFalse(r["is_instruction"], r["resource_id"])
            self.assertFalse(r["is_grant"], r["resource_id"])
            self.assertFalse(r["authorizes_execution"], r["resource_id"])

    def test_inventory_digests_match_recomputed(self):
        for r in onboarding.onboarding_inventory():
            if r.get("sha256") is None:
                continue
            # Recompute over exact bytes via the same accessor path.
            name = r["resource_name"]
            raw = (
                __import__("importlib.resources", fromlist=["files"])
                .files("epistates")
                .joinpath(*r["resource_subpath"], name)
                .read_bytes()
            )
            self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(), r["sha256"])

    def test_walkthrough_resource_declares_no_effects(self):
        wt = next(
            r for r in onboarding.onboarding_inventory() if r["resource_id"] == "walkthrough"
        )
        for flag in (
            "uses_subprocess", "uses_socket", "uses_clock", "uses_git",
            "uses_tmux", "uses_network",
        ):
            self.assertFalse(wt[flag], flag)


class ResourceAccessTests(unittest.TestCase):
    def test_agent_guide_readable_and_declares_disclaimer(self):
        text = onboarding.read_agent_guide()
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 100)
        self.assertIn("NOT", text.upper())
        # Declara explicitamente no instruccion / no grant.
        lowered = text.lower()
        self.assertTrue("instruction" in lowered or "grant" in lowered)

    def test_minimal_task_card_is_valid_and_ascii(self):
        raw = onboarding.read_minimal_task_card_text().encode("utf-8")
        raw.decode("ascii")  # ASCII puro
        card = onboarding.read_minimal_task_card()
        validate_task_card(card)  # pasa el validador normativo
        self.assertEqual(card["schema"], "epistates/task-card/v1")

    def test_minimal_card_digest_stable(self):
        self.assertEqual(
            onboarding.minimal_task_card_digest(),
            onboarding.minimal_task_card_digest(),
        )

    def test_minimal_card_object_is_fresh_copy(self):
        a = onboarding.read_minimal_task_card()
        b = onboarding.read_minimal_task_card()
        self.assertIsNot(a, b)
        a["task_id"] = "tampered"
        self.assertNotEqual(
            a["task_id"], onboarding.read_minimal_task_card()["task_id"]
        )

    def test_minimal_card_returned_already_validated_and_fresh(self):
        # El accessor devuelve una copia fresca ya validada: mutarla no afecta
        # a la siguiente llamada y el objeto retornado pasa validate_task_card.
        card = onboarding.read_minimal_task_card()
        validate_task_card(card)  # ya validada; sigue pasando
        card["authority"]["grant_id"] = "tampered-grant-id"
        fresh = onboarding.read_minimal_task_card()
        self.assertNotEqual(
            card["authority"]["grant_id"], fresh["authority"]["grant_id"]
        )
        validate_task_card(fresh)


# ---------------------------------------------------------------------------
# Fail-closed adversarial: digest corrupto, recurso ausente, UTF-8 invalido,
# JSON (dup key / NaN-Infinity / no objeto) y tarjeta semanticamente invalida.
# ---------------------------------------------------------------------------


class OnboardingFailClosedTests(unittest.TestCase):
    def _corrupt(self, *_a, **_k):
        return b"corrupt-bytes-not-matching-any-frozen-digest"

    def _missing(self, *_a, **_k):
        raise FileNotFoundError("missing")

    def test_guide_digest_corrupt_raises(self):
        with patch("epistates.onboarding._read_resource", side_effect=self._corrupt):
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_agent_guide()
            with self.assertRaises(OnboardingResourceError):
                onboarding.agent_guide_digest()

    def test_card_digest_corrupt_raises(self):
        with patch("epistates.onboarding._read_resource", side_effect=self._corrupt):
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_minimal_task_card_text()
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_minimal_task_card()
            with self.assertRaises(OnboardingResourceError):
                onboarding.minimal_task_card_digest()

    def test_missing_resource_raises_for_both_resources(self):
        with patch("epistates.onboarding._read_resource", side_effect=self._missing):
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_agent_guide()
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_minimal_task_card()

    def test_oserror_on_read_raises(self):
        def _oserr(*_a, **_k):
            raise OSError("io")
        with patch("epistates.onboarding._read_resource", side_effect=_oserr):
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_agent_guide()

    def test_invalid_utf8_raises(self):
        # Directo sobre el helper de decode.
        with self.assertRaises(OnboardingResourceError):
            onboarding._decode_utf8(b"\xff\xfe invalid utf8", "agent-guide.md")
        # Y via path integrado: bytes con digest correcto pero UTF-8 roto.
        bad = b"\xff\xfe\xfd"
        import hashlib as _h
        with patch("epistates.onboarding._read_resource", return_value=bad), \
             patch("epistates.onboarding._MINIMAL_CARD_DIGEST_HEX", _h.sha256(bad).hexdigest()):
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_minimal_task_card_text()

    def test_json_duplicate_key_raises(self):
        with self.assertRaises(OnboardingResourceError):
            onboarding._parse_json_strict('{"a": 1, "a": 2}', "minimal-task-card.json")

    def test_json_non_finite_constants_rejected(self):
        for payload in ("NaN", "Infinity", "-Infinity"):
            text = '{"x": ' + payload + "}"
            with self.assertRaises(OnboardingResourceError):
                onboarding._parse_json_strict(text, "minimal-task-card.json")

    def test_json_non_object_root_raises(self):
        for text in ("[1, 2, 3]", '"a string"', "42", "true", "null"):
            with self.assertRaises(OnboardingResourceError):
                onboarding._parse_json_strict(text, "minimal-task-card.json")

    def test_semantically_invalid_card_raises_end_to_end(self):
        # JSON bien formado, raiz objeto, digest correcto, pero la tarjeta no
        # pasa validate_task_card (schema equivocado).
        invalid = json.dumps({"schema": "epistates/not-real/v1"})
        raw = invalid.encode("utf-8")
        import hashlib as _h
        with patch("epistates.onboarding._read_resource", return_value=raw), \
             patch("epistates.onboarding._MINIMAL_CARD_DIGEST_HEX", _h.sha256(raw).hexdigest()):
            with self.assertRaises(OnboardingResourceError):
                onboarding.read_minimal_task_card()

    def test_error_messages_are_sanitized_no_host_paths(self):
        with patch("epistates.onboarding._read_resource", side_effect=self._corrupt):
            try:
                onboarding.read_agent_guide()
            except OnboardingResourceError as exc:
                msg = str(exc)
            else:
                self.fail("debio lanzar OnboardingResourceError")
        # El mensaje referencia el recurso, no rutas internas del host.
        self.assertIn("agent-guide.md", msg)
        for forbidden in ("/Users/", "/tmp/", "/Workspace/", "\\"):
            self.assertNotIn(forbidden, msg)

    def test_onboarding_resource_error_is_public_value_error(self):
        self.assertTrue(issubclass(OnboardingResourceError, ValueError))
        self.assertIn("OnboardingResourceError", onboarding.__all__)


class WalkthroughTests(unittest.TestCase):
    def test_walkthrough_returns_deterministic_text(self):
        a = onboarding.run_walkthrough()
        b = onboarding.run_walkthrough()
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))

    def test_walkthrough_reaches_done_and_declares_disclaimers(self):
        text = onboarding.run_walkthrough()
        self.assertIn("DONE", text)
        self.assertIn("NOT", text)
        # Declara que no uso efectos del host.
        self.assertIn("No subprocess", text)
        self.assertIn("walkthrough", text.lower())

    def test_walkthrough_writer_is_optional_and_pure(self):
        captured = []
        text = onboarding.run_walkthrough(writer=captured.append)
        self.assertTrue(captured)
        self.assertEqual("\n".join(captured) + "\n", text)

    def test_walkthrough_does_not_use_subprocess_socket_clock(self):
        def _boom(*a, **k):
            raise AssertionError("walkthrough probo subprocess/socket/red/reloj")

        patches = (
            patch("subprocess.run", side_effect=_boom),
            patch("subprocess.Popen", side_effect=_boom),
            patch("subprocess.call", side_effect=_boom),
            patch("subprocess.check_output", side_effect=_boom),
            patch("socket.socket", side_effect=_boom),
            patch("urllib.request.urlopen", side_effect=_boom),
            patch("time.time", side_effect=_boom),
            patch("time.monotonic", side_effect=_boom),
        )
        with _stack(patches):
            text = onboarding.run_walkthrough()
        self.assertIn("DONE", text)

    def test_walkthrough_does_not_write_filesystem(self):
        # Si no inyectamos writer, la funcion no debe abrir/escribir archivos.
        # Patcheamos open y os.open para asegurar pureza.
        def _boom_open(*a, **k):
            raise AssertionError("walkthrough abrio un archivo: %r" % (a,))

        with patch("builtins.open", side_effect=_boom_open):
            text = onboarding.run_walkthrough()
        self.assertIn("DONE", text)

    def test_walkthrough_real_process_is_deterministic_and_offline(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.abspath(SRC)
        script = (
            "from epistates.onboarding import run_walkthrough\n"
            "t = run_walkthrough()\n"
            "assert 'DONE' in t, t\n"
            "import sys; sys.stdout.write(t)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")


class OnboardingNoSubprocessImportTests(unittest.TestCase):
    def test_module_imports_no_subprocess_socket_urllib(self):
        source = inspect.getsource(onboarding)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertFalse(
                    name.startswith(("subprocess", "socket", "urllib")),
                    name,
                )


class DiscoveryParityTests(unittest.TestCase):
    def test_discovery_installable_resources_onboarding_matches_inventory(self):
        doc = build_discovery_document()
        inv = doc["installable_resources"]["onboarding"]["inventory"]
        local = onboarding.onboarding_inventory()
        self.assertEqual(
            [r["resource_id"] for r in inv],
            [r["resource_id"] for r in local],
        )
        for a, b in zip(inv, local):
            self.assertEqual(a.get("sha256"), b.get("sha256"))

    def test_discovery_onboarding_disclaims_authority(self):
        ob = build_discovery_document()["installable_resources"]["onboarding"]
        self.assertFalse(ob["is_instruction"])
        self.assertFalse(ob["is_grant"])
        self.assertFalse(ob["authorizes_execution"])


if __name__ == "__main__":
    unittest.main()
