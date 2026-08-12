import ast
import copy
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

from epistates import schemas
from epistates.__main__ import (
    _APPLICABLE,
    _VALIDATORS,
    build_schema_catalog_report,
    build_schema_show_report,
    main,
    render_schema_catalog_json,
    render_schema_show_json,
    schema_catalog_schema,
    schema_show_schema,
)
from epistates.discovery import build_discovery_document


FIXTURES = Path(__file__).parent.parent / "fixtures"
SRC = os.path.join(os.path.dirname(__file__), "..", "src")

_SEVEN_IDS = (
    "epistates/adapter-capabilities/v1",
    "epistates/audit-result/v1",
    "epistates/dispatch-receipt/v1",
    "epistates/human-notice/v1",
    "epistates/preflight-result/v1",
    "epistates/review-evidence/v1",
    "epistates/task-card/v1",
)


def _run_cli(*argv):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            result = main(list(argv))
            code = result if isinstance(result, int) else 0
        except SystemExit as caught:
            code = caught.code if isinstance(caught.code, int) else 2
    return code, out.getvalue(), err.getvalue()


def _stack(patches):
    stack = ExitStack()
    for patcher in patches:
        stack.enter_context(patcher)
    return stack


class FakeTraversable:
    def __init__(self, data: bytes):
        self._data = data

    def read_bytes(self) -> bytes:
        return self._data


def _raise_fnf(*a, **k):
    raise FileNotFoundError("missing")


# ---------------------------------------------------------------------------
# Catalogo: cerrado, inmutable, single-source, paridad.
# ---------------------------------------------------------------------------


class CatalogParityTests(unittest.TestCase):
    def test_catalog_has_exactly_seven_ids(self):
        self.assertEqual(set(schemas.schema_ids()), set(_SEVEN_IDS))
        self.assertEqual(schemas.schema_count(), 7)

    def test_ids_are_sorted_and_stable(self):
        self.assertEqual(schemas.schema_ids(), sorted(_SEVEN_IDS))
        self.assertEqual(schemas.schema_ids(), schemas.schema_ids())

    def test_recomputed_digests_match_catalog(self):
        for sid in schemas.schema_ids():
            desc = schemas.schema_descriptor(sid)
            actual = hashlib.sha256(schemas.read_schema_bytes(sid)).hexdigest()
            self.assertEqual("sha256:" + actual, desc["sha256"], sid)

    def test_schema_ids_match_main_validators(self):
        self.assertEqual(set(schemas.schema_ids()), set(_VALIDATORS.keys()))

    def test_descriptor_validator_is_normative_for_each_schema(self):
        for sid in schemas.schema_ids():
            desc = schemas.schema_descriptor(sid)
            callable_ = schemas.validator_callable(sid)
            self.assertEqual(callable_.__name__, desc["normative_validator"]["function"])
            self.assertEqual(
                callable_.__module__, desc["normative_validator"]["module"]
            )

    def test_required_bindings_match_main_applicability(self):
        for sid in schemas.schema_ids():
            desc = schemas.schema_descriptor(sid)
            self.assertEqual(
                set(desc["required_external_bindings"]),
                set(_APPLICABLE.get(sid, frozenset())),
                sid,
            )

    def test_every_descriptor_declares_authority_disclaimers(self):
        for desc in schemas.schema_catalog():
            self.assertEqual(desc["validation_scope"], "structural_only")
            self.assertFalse(desc["library_authenticates_authority"])
            self.assertFalse(desc["authorized_to_execute"])
            self.assertFalse(desc["provenance_verified"])
            self.assertEqual(desc["authority_status"], "external_unverified")
            self.assertTrue(desc["json_schema_id_is_identifier_only"])
            self.assertTrue(desc["json_schema_id_never_fetched"])

    def test_dollar_id_never_matches_resource_name_and_is_identifier(self):
        for desc in schemas.schema_catalog():
            self.assertTrue(desc["json_schema_id"].startswith("https://"))
            self.assertNotEqual(desc["json_schema_id"], desc["resource_name"])


# ---------------------------------------------------------------------------
# Schemas validos como JSON + sin claves duplicadas + ASCII puro.
# ---------------------------------------------------------------------------


class StructuralIntegrityTests(unittest.TestCase):
    def test_every_schema_is_valid_json_no_dup_keys_ascii(self):
        for sid in schemas.schema_ids():
            raw = schemas.read_schema_bytes(sid)
            raw.decode("ascii")  # ASCII puro
            doc = schemas.read_schema_document(sid)
            self.assertIsInstance(doc, dict, sid)

    def test_every_schema_declars_dollar_id_and_meta_schema(self):
        for sid in schemas.schema_ids():
            doc = schemas.read_schema_document(sid)
            self.assertIn("$id", doc)
            self.assertIn("$schema", doc)
            self.assertIn("title", doc)
            # $id is opaque identifier; this module never fetches it.
            self.assertTrue(doc["$id"].startswith("https://epistates.dev/"))

    def test_read_schema_text_is_utf8_and_matches_bytes(self):
        for sid in schemas.schema_ids():
            text = schemas.read_schema_text(sid)
            self.assertEqual(text.encode("utf-8"), schemas.read_schema_bytes(sid))

    def test_verify_schema_integrity_passes(self):
        schemas.verify_schema_integrity()  # no raise


# ---------------------------------------------------------------------------
# Schema vs validador Python: contraste (no equivalencia semantica).
# ---------------------------------------------------------------------------


class SchemaVsPythonValidatorTests(unittest.TestCase):
    """Cada schema es structural_only; el validador Python es normativo.

    Aqui probamos que cada schema + fixture valido pasa el validador Python, y
    que el descriptor declara honestamente structural_only. Los gaps semánticos
    (digests, binding, anti-TOCTOU) NO los expresa JSON Schema y se documentan.
    """

    def test_descriptor_declares_structural_only_and_names_normative(self):
        for sid in schemas.schema_ids():
            desc = schemas.schema_descriptor(sid)
            self.assertEqual(desc["validation_scope"], "structural_only")
            self.assertIn("function", desc["normative_validator"])
            self.assertIn("module", desc["normative_validator"])

    def test_valid_fixtures_pass_their_python_validator(self):
        pairs = [
            ("epistates/task-card/v1", "task-card-valid.json"),
            ("epistates/adapter-capabilities/v1", "adapter-capabilities-opencode-tmux.json"),
            ("epistates/audit-result/v1", "audit-result-valid.json"),
            ("epistates/preflight-result/v1", "preflight-result-ok.json"),
            ("epistates/dispatch-receipt/v1", "dispatch-receipt-ok.json"),
            ("epistates/human-notice/v1", "human-notice-ok.json"),
            ("epistates/review-evidence/v1", "review-evidence-ok.json"),
        ]
        for sid, fixture in pairs:
            validator = schemas.validator_callable(sid)
            with open(FIXTURES / fixture, encoding="utf-8") as handle:
                validator(json.load(handle))

    def test_invalid_fixtures_fail_their_python_validator(self):
        pairs = [
            ("epistates/task-card/v1", "task-card-missing-prohibitions.json"),
            ("epistates/adapter-capabilities/v1", "adapter-capabilities-bad-capability.json"),
            ("epistates/audit-result/v1", "audit-result-invalid-ok-missing.json"),
        ]
        for sid, fixture in pairs:
            validator = schemas.validator_callable(sid)
            with open(FIXTURES / fixture, encoding="utf-8") as handle:
                with self.assertRaises(Exception, msg=sid):
                    validator(json.load(handle))


# ---------------------------------------------------------------------------
# Fail-closed: id attacks, recurso ausente, digest divergente, contenido invalido.
# ---------------------------------------------------------------------------


class FailClosedTests(unittest.TestCase):
    def test_path_traversal_id_rejected(self):
        for bad in ("../task-card-v1.schema.json", "../../etc/passwd",
                    "epistates/../task-card/v1"):
            with self.assertRaises(schemas.SchemaError):
                schemas.schema_descriptor(bad), bad

    def test_absolute_path_id_rejected(self):
        with self.assertRaises(schemas.SchemaError):
            schemas.read_schema_bytes("/etc/passwd")

    def test_percent_encoded_id_rejected(self):
        with self.assertRaises(schemas.SchemaError):
            schemas.read_schema_bytes("%2e%2e/task-card/v1")

    def test_unknown_id_rejected(self):
        with self.assertRaises(schemas.SchemaError):
            schemas.schema_descriptor("epistates/does-not-exist/v1")

    def test_empty_and_non_string_id_rejected(self):
        with self.assertRaises(schemas.SchemaError):
            schemas.schema_descriptor("")
        with self.assertRaises(schemas.SchemaError):
            schemas.schema_descriptor(None)
        with self.assertRaises(schemas.SchemaError):
            schemas.schema_descriptor(123)

    def test_control_chars_in_id_rejected(self):
        for cp in (0x00, 0x0A, 0x0D, 0x1B, 0x7F, 0x85, 0x9B):
            sid = "epistates/task" + chr(cp) + "-card/v1"
            with self.assertRaises(schemas.SchemaError):
                schemas.schema_descriptor(sid)

    def test_unicode_confusable_id_rejected(self):
        # 'a' cirilica (U+0430) no es la 'a' latina del catalogo.
        sid = "epistates/t" + "\u0430" + "sk-card/v1"
        with self.assertRaises(schemas.SchemaError):
            schemas.schema_descriptor(sid)

    def test_digest_mismatch_on_corrupt_resource(self):
        # Simula un recurso empaquetado corrupto: read_bytes devuelve otros bytes.
        with patch("epistates.schemas.files") as mock_files:
            mock_files.return_value.joinpath.return_value = FakeTraversable(b"{}")
            with self.assertRaises(schemas.SchemaError) as ctx:
                schemas.read_schema_bytes("epistates/task-card/v1")
            self.assertIn("digest", str(ctx.exception).lower())

    def test_missing_resource_file_raises(self):
        with patch("epistates.schemas.files") as mock_files:
            mock_files.return_value.joinpath.return_value = FakeTraversable(b"")
            mock_files.return_value.joinpath.return_value.read_bytes = _raise_fnf
            with self.assertRaises(schemas.SchemaError):
                schemas.read_schema_bytes("epistates/task-card/v1")


# ---------------------------------------------------------------------------
# Aislamiento: mutar respuestas no contamina.
# ---------------------------------------------------------------------------


class IsolationTests(unittest.TestCase):
    def test_descriptor_returns_fresh_copy(self):
        a = schemas.schema_descriptor("epistates/task-card/v1")
        b = schemas.schema_descriptor("epistates/task-card/v1")
        self.assertIsNot(a, b)
        a["sha256"] = "tampered"
        self.assertNotEqual(
            a["sha256"],
            schemas.schema_descriptor("epistates/task-card/v1")["sha256"],
        )

    def test_catalog_returns_fresh_list(self):
        cat1 = schemas.schema_catalog()
        cat2 = schemas.schema_catalog()
        self.assertIsNot(cat1, cat2)
        cat1.append({"injected": True})
        cat1[0]["sha256"] = "tampered"
        self.assertEqual(len(cat2), 7)
        self.assertNotIn("injected", cat2[0])

    def test_read_bytes_returns_fresh_bytes(self):
        b1 = bytearray(schemas.read_schema_bytes("epistates/task-card/v1"))
        b1[0] = 0
        b2 = schemas.read_schema_bytes("epistates/task-card/v1")
        self.assertNotEqual(bytes(b1), b2)
        # La constante interna no se altera:
        schemas.read_schema_document("epistates/task-card/v1")

    def test_document_returns_fresh_dict(self):
        d1 = schemas.read_schema_document("epistates/task-card/v1")
        d2 = schemas.read_schema_document("epistates/task-card/v1")
        self.assertIsNot(d1, d2)
        d1["$id"] = "tampered"
        self.assertNotEqual(
            d1["$id"],
            schemas.read_schema_document("epistates/task-card/v1")["$id"],
        )

    def test_deepcopy_aggressive_mutation_does_not_propagate(self):
        baseline = copy.deepcopy(schemas.schema_catalog())
        polluted = schemas.schema_catalog()
        for entry in polluted:
            entry["sha256"] = "x"
            entry["normative_validator"]["function"] = "x"
        self.assertEqual(
            [e["sha256"] for e in baseline],
            [e["sha256"] for e in schemas.schema_catalog()],
        )


# ---------------------------------------------------------------------------
# CLI: schema list / schema show.
# ---------------------------------------------------------------------------


class SchemaCliTests(unittest.TestCase):
    def test_schema_list_exits_zero_empty_stderr_single_json(self):
        code, out, err = _run_cli("schema", "list", "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(out.endswith("\n"))
        doc = json.loads(out)
        self.assertEqual(doc["schema"], schema_catalog_schema())
        self.assertEqual(len(doc["catalog"]), 7)
        self.assertFalse(doc["authorized_to_execute"])
        self.assertFalse(doc["provenance_verified"])

    def test_schema_show_exits_zero_with_schema_and_descriptor(self):
        code, out, err = _run_cli(
            "schema", "show", "epistates/task-card/v1", "--format", "json"
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(doc["schema"], schema_show_schema())
        self.assertEqual(doc["schema_id"], "epistates/task-card/v1")
        self.assertIn("$id", doc["json_schema"])
        self.assertEqual(doc["descriptor"]["validation_scope"], "structural_only")

    def test_schema_show_unknown_id_exits_one(self):
        code, out, err = _run_cli("schema", "show", "epistates/nope/v1", "--format", "json")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertNotEqual(err, "")

    def test_schema_list_missing_format_exits_two(self):
        self.assertEqual(_run_cli("schema", "list")[0], 2)

    def test_schema_show_missing_format_exits_two(self):
        self.assertEqual(
            _run_cli("schema", "show", "epistates/task-card/v1")[0], 2
        )

    def test_schema_no_subcommand_exits_two(self):
        self.assertEqual(_run_cli("schema")[0], 2)

    def test_schema_show_attack_ids_exit_one(self):
        for bad in ("../x", "%2e%2e/x", "epistates/../x", "/abs/path"):
            code, out, err = _run_cli("schema", "show", bad, "--format", "json")
            self.assertEqual(code, 1, bad)
            self.assertEqual(out, "", bad)

    def test_schema_list_byte_identical_across_runs(self):
        a = render_schema_catalog_json()
        b = render_schema_catalog_json()
        self.assertEqual(a, b)

    def test_schema_show_byte_identical_across_runs(self):
        a = render_schema_show_json("epistates/audit-result/v1")
        b = render_schema_show_json("epistates/audit-result/v1")
        self.assertEqual(a, b)

    def test_schema_outputs_are_ascii(self):
        render_schema_catalog_json().encode("ascii")
        for sid in schemas.schema_ids():
            render_schema_show_json(sid).encode("ascii")


# ---------------------------------------------------------------------------
# No probing: subprocess/socket/clock/terminal bloqueados durante schema list/show.
# ---------------------------------------------------------------------------


class NoProbingTests(unittest.TestCase):
    def _patches(self):
        def _boom(*a, **k):
            raise AssertionError("prohibido subprocess/socket/red/reloj/terminal")

        return (
            patch("subprocess.run", side_effect=_boom),
            patch("subprocess.Popen", side_effect=_boom),
            patch("subprocess.call", side_effect=_boom),
            patch("subprocess.check_output", side_effect=_boom),
            patch("socket.socket", side_effect=_boom),
            patch("urllib.request.urlopen", side_effect=_boom),
            patch("shutil.get_terminal_size", side_effect=_boom),
            patch("os.get_terminal_size", side_effect=_boom),
            patch("time.time", side_effect=_boom),
            patch("time.monotonic", side_effect=_boom),
        )

    def test_schema_list_does_not_probe(self):
        with _stack(self._patches()):
            code, out, err = _run_cli("schema", "list", "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_schema_show_does_not_probe(self):
        with _stack(self._patches()):
            code, out, err = _run_cli(
                "schema", "show", "epistates/task-card/v1", "--format", "json"
            )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_schemas_module_imports_no_subprocess_socket_urllib(self):
        source = inspect.getsource(schemas)
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


# ---------------------------------------------------------------------------
# Determinismo ante locale / TZ (proceso real).
# ---------------------------------------------------------------------------


class RealProcessLocaleTests(unittest.TestCase):
    def _run_module(self, *argv, extra_env=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.abspath(SRC)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "epistates", *argv],
            capture_output=True, env=env,
        )

    def test_schema_list_stable_across_locale_tz(self):
        base = self._run_module("schema", "list", "--format", "json")
        self.assertEqual(base.returncode, 0, base.stderr)
        for env in (
            {"PYTHONIOENCODING": "ascii", "LC_ALL": "C", "TZ": "UTC"},
            {"LC_ALL": "ja_JP.UTF-8", "TZ": "Asia/Tokyo"},
        ):
            other = self._run_module("schema", "list", "--format", "json", extra_env=env)
            self.assertEqual(other.returncode, 0, other.stderr)
            self.assertEqual(other.stdout, base.stdout)
            self.assertEqual(other.stderr, b"")


# ---------------------------------------------------------------------------
# Paridad discovery <-> schemas.
# ---------------------------------------------------------------------------


class DiscoveryParityTests(unittest.TestCase):
    def test_discovery_installable_resources_match_catalog(self):
        doc = build_discovery_document()
        ir = doc["installable_resources"]["schemas"]
        self.assertEqual(ir["schema_ids"], schemas.schema_ids())
        self.assertEqual(
            [d["schema_id"] for d in ir["catalog"]],
            [d["schema_id"] for d in schemas.schema_catalog()],
        )
        # Digests coherentes discovery vs accessor.
        for d_ir, d_acc in zip(ir["catalog"], schemas.schema_catalog()):
            self.assertEqual(d_ir["sha256"], d_acc["sha256"])

    def test_discovery_describes_authority_disclaimers(self):
        ir = build_discovery_document()["installable_resources"]["schemas"]
        self.assertFalse(ir["library_authenticates_authority"])
        self.assertFalse(ir["authorized_to_execute"])
        self.assertTrue(ir["json_schema_ids_never_fetched"])

    def test_output_schemas_include_schema_commands(self):
        from epistates.discovery import output_schemas
        out = output_schemas()
        self.assertIn(schema_catalog_schema(), out)
        self.assertIn(schema_show_schema(), out)


if __name__ == "__main__":
    unittest.main()
