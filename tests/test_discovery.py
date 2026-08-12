import argparse
import copy
import importlib
import inspect
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from unittest.mock import patch

import epistates
from epistates import _version
from epistates.adapter import _CAPABILITY_IDS
from epistates.capabilities import CAPABILITY_IDS, capability_descriptors
from epistates.discovery import (
    DISCOVERY_SCHEMA,
    build_discovery_document,
    cataloged_symbol_names,
    capability_ids,
    render_discovery_json,
    validatable_schemas,
)
from epistates.__main__ import (
    _AUDIT_DECISION_OPTIONS,
    _REVIEW_BINDING_OPTIONS,
    _VALIDATORS,
    _escape_control_chars,
    _format_applicability_matrix,
    _build_parser,
    main,
)


SRC = os.path.join(os.path.dirname(__file__), "..", "src")


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


def _all_entries(doc):
    return (
        doc["public_api"]["metadata"]
        + doc["public_api"]["types"]
        + doc["public_api"]["errors"]
        + doc["public_api"]["operations"]
    )


def _operations(doc):
    return doc["public_api"]["operations"]


def _types(doc):
    return doc["public_api"]["types"]


def _cli_surface(doc):
    return doc["capability_planes"]["catalog"]["cli_surface"]


# ---------------------------------------------------------------------------
# Estructura, declaraciones, single-source y provenance.
# ---------------------------------------------------------------------------


class StructureAndProvenanceTests(unittest.TestCase):
    def test_schema_and_version(self):
        doc = build_discovery_document()
        self.assertEqual(doc["schema"], DISCOVERY_SCHEMA)
        self.assertEqual(doc["package_version"], epistates.__version__)

    def test_declarations_explicit(self):
        d = build_discovery_document()["declarations"]
        self.assertTrue(d["not_authority"])
        self.assertTrue(d["not_observed"])
        self.assertFalse(d["performs_host_probing"])
        self.assertTrue(d["static_only"])
        self.assertFalse(d["epistates_authenticates_grants"])

    def test_authority_provenance_disclaims_grant_authentication(self):
        ap = build_discovery_document()["authority_provenance"]
        self.assertEqual(ap["task_card_authority"], "self_declarable_correlation_only")
        self.assertEqual(ap["vigent_authority_source"], "external_control_plane")
        self.assertFalse(ap["epistates_authenticates_grants"])
        self.assertIn("control-plane", ap["description"])


# ---------------------------------------------------------------------------
# Aislamiento (deepcopy): mutar una respuesta no afecta las demás ni constantes.
# ---------------------------------------------------------------------------


class DeepIsolationTests(unittest.TestCase):
    def test_baseline_returned_fresh_each_call(self):
        self.assertNotEqual(
            id(build_discovery_document()), id(build_discovery_document())
        )

    def test_aggressive_mutation_does_not_propagate(self):
        baseline = copy.deepcopy(build_discovery_document())
        polluted = build_discovery_document()
        # Mutar agresivamente estructuras anidadas.
        for op in polluted["public_api"]["operations"]:
            op["cli_exposure"]["mode"] = "TAMPERED"
            op["platforms"].append("tampered")
        for tp in polluted["public_api"]["types"]:
            for method in tp.get("methods", []):
                method["effect_class"] = "TAMPERED"
                method["platforms"].append("tampered")
            tp.setdefault("methods", []).append({"name": "tampered"})
        polluted["capability_planes"]["catalog"]["adapter_capabilities"].append(
            {"id": "tampered"}
        )
        for entry in _cli_surface(polluted):
            entry["retry_safety"] = "TAMPERED"
        polluted["runtime_requirements"]["platforms_by_effect_class"]["pure_compute"].append("z")
        polluted["enums"]["effect_class"].append("TAMPERED")
        polluted["implementation"]["code_in_package"] = "TAMPERED"
        # Una nueva respuesta debe ser idéntica al baseline original.
        again = build_discovery_document()
        self.assertEqual(again, baseline)

    def test_module_constants_not_corrupted(self):
        from epistates import discovery as d

        before_ops = copy.deepcopy(d._OPERATIONS)
        before_types = copy.deepcopy(d._TYPES)
        before_cli = copy.deepcopy(d._CLI_SURFACE)
        doc = build_discovery_document()
        doc["public_api"]["operations"][0]["cli_exposure"]["mode"] = "X"
        doc["public_api"]["operations"][0]["platforms"].clear()
        if doc["public_api"]["types"][0].get("methods"):
            doc["public_api"]["types"][0]["methods"].clear()
        self.assertEqual(d._OPERATIONS, before_ops)
        self.assertEqual(d._TYPES, before_types)
        self.assertEqual(d._CLI_SURFACE, before_cli)


# ---------------------------------------------------------------------------
# Cobertura de __all__ + identidad module/kind por introspección.
# ---------------------------------------------------------------------------


class AllCoverageAndIdentityTests(unittest.TestCase):
    def test_catalog_covers_exactly_all(self):
        self.assertEqual(set(epistates.__all__), set(cataloged_symbol_names()))

    def test_symbol_module_and_kind_match_introspection(self):
        for entry in _all_entries(build_discovery_document()):
            module = importlib.import_module(entry["module"])
            obj = getattr(module, entry["name"])
            kind = entry["kind"]
            if kind == "metadata":
                self.assertIsInstance(obj, str, entry["name"])
            elif kind == "error":
                self.assertTrue(
                    isinstance(obj, type) and issubclass(obj, Exception),
                    entry["name"],
                )
            elif kind == "type":
                self.assertTrue(isinstance(obj, type), entry["name"])
                self.assertFalse(issubclass(obj, Exception), entry["name"])
            elif kind == "operation":
                self.assertTrue(callable(obj) and not isinstance(obj, type), entry["name"])


# ---------------------------------------------------------------------------
# Enums cerrados.
# ---------------------------------------------------------------------------


class ClosedEnumsTests(unittest.TestCase):
    def test_all_enums_closed(self):
        doc = build_discovery_document()
        enums = doc["enums"]
        # operations / types / cli_surface / capabilities / methods
        for op in _operations(doc):
            self.assertIn(op["effect_class"], enums["effect_class"], op["name"])
            self.assertIn(op["retry_safety"], enums["retry_safety"], op["name"])
            self.assertIn(op["authority_enforcement"], enums["authority_enforcement"], op["name"])
            self.assertIn(op["cli_exposure"]["mode"], enums["invocation_mode"], op["name"])
        for tp in _types(doc):
            self.assertIn(tp["effect_class"], enums["effect_class"], tp["name"])
            for method in tp.get("methods", []):
                self.assertIn(method["effect_class"], enums["effect_class"], tp["name"])
                self.assertIn(method["retry_safety"], enums["retry_safety"], tp["name"])
        for entry in _cli_surface(doc):
            self.assertIn(entry["effect_class"], enums["effect_class"], entry["name"])
            self.assertIn(entry["retry_safety"], enums["retry_safety"], entry["name"])
            self.assertIn(
                entry["authority_enforcement"], enums["authority_enforcement"], entry["name"]
            )
        for cap in doc["capability_planes"]["catalog"]["adapter_capabilities"]:
            self.assertIn(cap["effect_class"], enums["effect_class"], cap["id"])
            self.assertIn(cap["retry_safety"], enums["retry_safety"], cap["id"])
        for plane in doc["capability_planes"].values():
            self.assertIn(plane["status"], enums["capability_plane_status"])
        impl = doc["implementation"]
        for key in ("code_in_package", "host_runtime_available", "adapter_live",
                    "authority_granted"):
            self.assertIn(impl[key], enums["implementation_signal"], key)

    def test_filesystem_read_and_authority_enforcement_present(self):
        enums = build_discovery_document()["enums"]
        self.assertIn("filesystem_read", enums["effect_class"])
        self.assertEqual(
            enums["authority_enforcement"],
            ["not_required", "external_control_plane", "caller_responsibility"],
        )


# ---------------------------------------------------------------------------
# Invariantes de autoridad y efectos.
# ---------------------------------------------------------------------------


_HOST_CONTACT = {"host_observation", "terminal_write", "project_code_execution"}
_MUTATING = {"terminal_write", "project_code_execution"}


class AuthorityInvariantTests(unittest.TestCase):
    def test_host_contact_requires_authority_and_external_control_plane(self):
        for op in _operations(build_discovery_document()):
            if op["effect_class"] in _HOST_CONTACT:
                self.assertTrue(op["requires_external_authority"], op["name"])
                self.assertEqual(op["authority_enforcement"], "external_control_plane", op["name"])

    def test_write_and_code_execution_mutate(self):
        for op in _operations(build_discovery_document()):
            if op["effect_class"] in _MUTATING:
                self.assertTrue(op["may_mutate_host"], op["name"])

    def test_apply_audit_and_transition_coherent_require_authority(self):
        doc = build_discovery_document()
        for name in ("apply_audit", "apply_audit_from_review", "transition"):
            op = next(o for o in _operations(doc) if o["name"] == name)
            self.assertEqual(op["effect_class"], "pure_compute", name)
            self.assertTrue(op["requires_external_authority"], name)
            self.assertFalse(op["may_mutate_host"], name)

    def test_apply_audit_uses_external_control_plane(self):
        doc = build_discovery_document()
        for name in ("apply_audit", "apply_audit_from_review"):
            op = next(o for o in _operations(doc) if o["name"] == name)
            self.assertEqual(op["authority_enforcement"], "external_control_plane", name)

    def test_transition_is_caller_responsibility_proposal(self):
        op = next(
            o for o in _operations(build_discovery_document()) if o["name"] == "transition"
        )
        self.assertEqual(op["authority_enforcement"], "caller_responsibility")

    def test_pure_validators_are_not_required(self):
        doc = build_discovery_document()
        for op in _operations(doc):
            if op["name"].startswith("validate_") or op["name"] in (
                "canonical_digest", "evaluate_preflight", "build_discovery_document",
            ):
                self.assertEqual(op["authority_enforcement"], "not_required", op["name"])
                self.assertFalse(op["requires_external_authority"], op["name"])

    def test_validate_cli_is_filesystem_read_and_requires_authority(self):
        entry = next(
            e for e in _cli_surface(build_discovery_document()) if e["name"] == "validate"
        )
        self.assertEqual(entry["effect_class"], "filesystem_read")
        self.assertTrue(entry["requires_external_authority"])
        self.assertEqual(entry["authority_enforcement"], "caller_responsibility")

    def test_cli_surface_entries_declare_full_metadata(self):
        for entry in _cli_surface(build_discovery_document()):
            for key in (
                "effect_class", "requires_external_authority", "may_mutate_host",
                "authority_enforcement", "library_authenticates_authority",
                "binding_behavior", "retry_safety",
            ):
                self.assertIn(key, entry, entry["name"])
            self.assertFalse(entry["library_authenticates_authority"])


# ---------------------------------------------------------------------------
# cli_exposure: library_only serializa subcommand null; no direct invocation.
# ---------------------------------------------------------------------------


class CliExposureTests(unittest.TestCase):
    def test_no_operation_directly_invocable(self):
        for op in _operations(build_discovery_document()):
            self.assertFalse(op["cli_exposure"]["directly_invocable"], op["name"])

    def test_library_only_serializes_subcommand_null(self):
        doc = build_discovery_document()
        for op in _operations(doc):
            if op["cli_exposure"]["mode"] == "library_only":
                self.assertIsNone(op["cli_exposure"]["subcommand"], op["name"])
        # Y se serializa como JSON null (no string vacío).
        text = render_discovery_json()
        self.assertIn('"subcommand": null', text)
        self.assertNotIn('"subcommand": ""', text)

    def test_validate_and_describe_name_composite_subcommand(self):
        doc = build_discovery_document()
        targets = {
            "build_discovery_document": "describe",
        }
        for op in _operations(doc):
            if op["name"].startswith("validate_"):
                targets[op["name"]] = "validate"
        for name, sub in targets.items():
            op = next(o for o in _operations(doc) if o["name"] == name)
            self.assertEqual(op["cli_exposure"]["subcommand"], sub, name)


# ---------------------------------------------------------------------------
# Metadata por método: introspección REAL de clases/protocols concretas.
# ---------------------------------------------------------------------------


class MethodIntrospectionTests(unittest.TestCase):
    def _public_methods(self, cls):
        names = set()
        for name in dir(cls):
            if name.startswith("_"):
                continue
            attr = getattr(cls, name)
            if callable(attr) and not isinstance(attr, type):
                names.add(name)
        return names

    def test_cataloged_methods_match_real_class_introspection(self):
        from epistates.host_runner import ProductionHostRunner, HostRunner
        from epistates.dispatch import TmuxLiteralDispatcher, LiteralDispatcher
        from epistates.review_runner import TmuxReviewRunner, ReviewRunner

        doc = build_discovery_document()
        catalog = {t["name"]: {m["name"] for m in t.get("methods", [])} for t in _types(doc)}
        for cls in (
            ProductionHostRunner, HostRunner, TmuxLiteralDispatcher,
            LiteralDispatcher, TmuxReviewRunner, ReviewRunner,
        ):
            real = self._public_methods(cls)
            self.assertEqual(catalog[cls.__name__], real, cls.__name__)

    def test_data_types_have_no_methods(self):
        doc = build_discovery_document()
        for tp in _types(doc):
            if tp["nature"] in ("named_tuple", "typed_dict"):
                self.assertNotIn("methods", tp, tp["name"])

    def test_run_check_is_project_code_execution_in_catalog(self):
        for tp in _types(build_discovery_document()):
            for method in tp.get("methods", []):
                if method["name"] == "run_check":
                    self.assertEqual(method["effect_class"], "project_code_execution")
                    self.assertTrue(method["may_mutate_host"])


# ---------------------------------------------------------------------------
# Paridad real con fuentes normativas.
# ---------------------------------------------------------------------------


class SharedSourceParityTests(unittest.TestCase):
    def test_capability_ids_match_adapter_and_capabilities_module(self):
        self.assertEqual(set(capability_ids()), set(_CAPABILITY_IDS))
        self.assertEqual(set(capability_ids()), set(CAPABILITY_IDS))

    def test_catalog_publishes_full_capability_descriptors(self):
        published = build_discovery_document()["capability_planes"]["catalog"][
            "adapter_capabilities"]
        self.assertEqual(
            [c["id"] for c in published],
            [c["id"] for c in capability_descriptors()],
        )
        for cap in published:
            for key in (
                "id", "surface", "effect_class", "requires_external_authority",
                "may_mutate_host", "retry_safety", "runtime_enforced",
                "enforcement_owner", "library_authenticates_authority",
                "description",
            ):
                self.assertIn(key, cap, cap.get("id"))
            self.assertFalse(cap["runtime_enforced"])
            self.assertEqual(cap["enforcement_owner"], "external_control_plane")
            self.assertFalse(cap["library_authenticates_authority"])

    def test_capability_accessor_is_mutation_isolated(self):
        baseline = capability_descriptors()
        polluted = capability_descriptors()
        polluted[0]["id"] = "injected_capability"
        polluted[0]["runtime_enforced"] = True
        polluted.append({"id": "another_injection"})

        fresh = capability_descriptors()
        published = build_discovery_document()["capability_planes"]["catalog"][
            "adapter_capabilities"]
        self.assertEqual(fresh, baseline)
        self.assertEqual(published, baseline)
        self.assertEqual({c["id"] for c in fresh}, set(CAPABILITY_IDS))
        self.assertNotIn("injected_capability", _CAPABILITY_IDS)
        dispatch = next(c for c in fresh if c["id"] == "dispatch_literal")
        self.assertEqual(dispatch["effect_class"], "terminal_write")
        self.assertFalse(dispatch["runtime_enforced"])

    def test_schemas_validatable_match_cli_validators(self):
        self.assertEqual(set(validatable_schemas()), set(_VALIDATORS.keys()))


# ---------------------------------------------------------------------------
# Plano de implementación y requisitos de runtime.
# ---------------------------------------------------------------------------


class ImplementationAndRuntimeTests(unittest.TestCase):
    def test_implementation_conservative(self):
        impl = build_discovery_document()["implementation"]
        self.assertEqual(impl["code_in_package"], "implemented_in_source")
        for key in ("host_runtime_available", "adapter_live", "authority_granted"):
            self.assertEqual(impl[key], "not_observed", key)

    def test_runtime_requirements_declared(self):
        req = build_discovery_document()["runtime_requirements"]
        self.assertEqual(req["python_min"], "3.9")
        self.assertEqual(req["python_min_source"], "declared_package_metadata")
        self.assertEqual(req["platforms_by_effect_class"]["pure_compute"], ["any"])
        self.assertIn("tmux", req["potential_executables_by_effect_class"]["terminal_write"])
        self.assertIn("no requisito all_of", req["potential_executables_semantics"])

    def test_exact_executable_requirements_are_per_method(self):
        methods = {
            method["name"]: method
            for tp in _types(build_discovery_document())
            for method in tp.get("methods", [])
        }
        self.assertEqual(methods["git_status"]["executables"], ["git"])
        self.assertEqual(methods["tmux_list_panes"]["executables"], ["tmux"])
        self.assertEqual(methods["capture_once"]["executables"], ["tmux"])
        self.assertEqual(methods["send_literal_text"]["executables"], ["tmux"])
        self.assertEqual(
            methods["run_check"]["executable_requirement"],
            "conditional_by_check_id",
        )
        self.assertEqual(
            methods["run_check"]["executables_by_check_id"],
            {
                "git_status": ["git"],
                "diff_check": ["git"],
                "unit_tests": ["python"],
            },
        )

    def test_python_min_matches_pyproject(self):
        path = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(path, encoding="utf-8") as handle:
            pyproject = handle.read()
        match = __import__("re").search(
            r'^requires-python\s*=\s*">=([0-9]+\.[0-9]+)"',
            pyproject,
            __import__("re").MULTILINE,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            build_discovery_document()["runtime_requirements"]["python_min"],
            match.group(1),
        )


# ---------------------------------------------------------------------------
# Parser <-> cli_surface y help completo (introspección del parser real).
# ---------------------------------------------------------------------------


def _subparsers_action(parser):
    return next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )


class ParserManifestTests(unittest.TestCase):
    def test_cli_surface_subcommands_match_parser(self):
        parser = _build_parser()
        defined = set(_subparsers_action(parser).choices.keys())
        surface_subs = {
            e["name"] for e in _cli_surface(build_discovery_document())
            if e["kind"] == "subcommand"
        }
        self.assertEqual(defined, surface_subs)

    def test_validate_parser_has_help_on_all_public_actions(self):
        parser = _build_parser()
        validate = _subparsers_action(parser).choices["validate"]
        for action in validate._actions:
            # help action (-h) y flags internas pueden tener help; las públicas no.
            if action.option_strings or action.dest == "card":
                self.assertIsNotNone(action.help, action.dest)
                self.assertNotEqual(action.help, argparse.SUPPRESS, action.dest)

    def test_validate_parser_option_count(self):
        parser = _build_parser()
        validate = _subparsers_action(parser).choices["validate"]
        options = [
            a for a in validate._actions
            if a.option_strings and a.option_strings[0] not in ("-h", "--help")
        ]
        # 21 opciones de binding (sin -h).
        self.assertEqual(len(options), 21)

    def test_bridge_matrix_lists_explicit_complete_set(self):
        matrix = _format_applicability_matrix()
        bridge_expected = set(_REVIEW_BINDING_OPTIONS) | set(_AUDIT_DECISION_OPTIONS)
        for name in bridge_expected:
            self.assertIn("--" + name.replace("_", "-"), matrix, name)
        # No debe usar la frase ambigua "todas las anteriores".
        self.assertNotIn("TODAS las anteriores", matrix)


# ---------------------------------------------------------------------------
# Determinismo y ASCII-safe.
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_two_renders_byte_identical(self):
        self.assertEqual(render_discovery_json(), render_discovery_json())

    def test_render_is_single_ascii_json(self):
        text = render_discovery_json()
        self.assertTrue(text.endswith("\n"))
        text.encode("ascii")
        json.loads(text)

    def test_render_stable_across_locale_and_timezone(self):
        baseline = render_discovery_json()
        saved = {k: os.environ.get(k) for k in ("LC_ALL", "TZ")}
        try:
            for env in ({"LC_ALL": "C", "TZ": "UTC"},
                        {"LC_ALL": "ja_JP.UTF-8", "TZ": "Asia/Tokyo"}):
                for k, v in env.items():
                    os.environ[k] = v
                self.assertEqual(render_discovery_json(), baseline)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


# ---------------------------------------------------------------------------
# No-probing + no mutación de streams del caller.
# ---------------------------------------------------------------------------


class NoProbingAndStreamSafetyTests(unittest.TestCase):
    def _patches(self):
        def _boom(*a, **k):
            raise AssertionError("prohibido subprocess/socket/red")

        return (
            patch("subprocess.run", side_effect=_boom),
            patch("subprocess.Popen", side_effect=_boom),
            patch("subprocess.call", side_effect=_boom),
            patch("subprocess.check_output", side_effect=_boom),
            patch("socket.socket", side_effect=_boom),
            patch("urllib.request.urlopen", side_effect=_boom),
            patch("shutil.get_terminal_size", side_effect=_boom),
            patch("os.get_terminal_size", side_effect=_boom),
        )

    def test_describe_version_help_do_not_probe(self):
        for argv in (["--version"], ["describe", "--format", "json"], ["--help"]):
            with _stack(self._patches()):
                code, out, err = _run_cli(*argv)
            self.assertEqual(code, 0, argv)

    def test_subcommand_help_does_not_query_terminal_size(self):
        for argv in (["validate", "--help"], ["describe", "--help"]):
            with _stack(self._patches()):
                code, out, err = _run_cli(*argv)
            self.assertEqual(code, 0, argv)

    def test_main_does_not_reconfigure_caller_streams(self):
        reconfigured = []

        class FakeStream(io.StringIO):
            def reconfigure(self, **kwargs):
                reconfigured.append(kwargs)

        out, err = FakeStream(), FakeStream()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                main(["describe", "--format", "json"])
            except SystemExit:
                pass
        self.assertEqual(reconfigured, [])

    def test_discovery_module_imports_no_subprocess_no_socket(self):
        import ast as _ast
        from epistates import discovery as d
        source = inspect.getsource(d)
        for node in _ast.walk(_ast.parse(source)):
            if isinstance(node, _ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, _ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertFalse(name.startswith(("subprocess", "socket", "urllib")), name)

    def test_real_process_startup_does_not_probe(self):
        script = (
            "import subprocess as sp, socket, sys\n"
            "def _boom(*a, **k):\n"
            "    raise AssertionError('startup probe blocked')\n"
            "sp.run = sp.Popen = sp.call = sp.check_output = _boom\n"
            "socket.socket = _boom\n"
            "import importlib\n"
            "importlib.import_module('epistates')\n"
            "from epistates.__main__ import main\n"
            "sys.exit(main(['describe', '--format', 'json']) or 0)\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.abspath(SRC)
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        json.loads(result.stdout)
        self.assertEqual(result.stderr, b"")


class DocumentationInvariantTests(unittest.TestCase):
    def _guide(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "docs", "agent-integration.md"
        )
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_transition_table_requires_external_authority(self):
        guide = self._guide()
        row = next(
            line for line in guide.splitlines() if line.startswith("| `transition` |")
        )
        self.assertIn("| **sí** |", row)

    def test_guide_freezes_authority_and_capability_boundaries(self):
        guide = self._guide()
        for statement in (
            "task-card.authority` es **solo",
            "library_authenticates_authority == false",
            "`runtime_enforced: false`",
            "**no funciona como gate de runtime**",
        ):
            self.assertIn(statement, guide)


# ---------------------------------------------------------------------------
# CLI behaviour.
# ---------------------------------------------------------------------------


class CliBehaviourTests(unittest.TestCase):
    def test_version_exits_zero(self):
        code, out, err = _run_cli("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), epistates.__version__)
        self.assertEqual(err, "")

    def test_describe_single_json_empty_stderr(self):
        code, out, err = _run_cli("describe", "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out, render_discovery_json())

    def test_describe_requires_format_exit2(self):
        self.assertEqual(_run_cli("describe")[0], 2)

    def test_validate_output_unchanged(self):
        from pathlib import Path
        fixtures = Path(__file__).parent.parent / "fixtures"
        ok, out_ok, _ = _run_cli("validate", str(fixtures / "task-card-valid.json"))
        bad, out_bad, _ = _run_cli("validate", str(fixtures / "audit-result-valid.json"))
        self.assertEqual(ok, 0)
        self.assertIn("VALID", out_ok)
        self.assertEqual(bad, 1)
        self.assertIn("INVALID", out_bad)


# ---------------------------------------------------------------------------
# Sanitizador Cc (C0 + DEL + C1) por proceso real y a nivel de función.
# ---------------------------------------------------------------------------


class CcSanitizerTests(unittest.TestCase):
    def test_escape_control_chars_function_covers_c0_del_c1_and_nul(self):
        for cp in (0x00, 0x0A, 0x0D, 0x1B, 0x7F, 0x85, 0x9B, 0x9F):
            self.assertNotIn(chr(cp), _escape_control_chars("a" + chr(cp) + "b"), hex(cp))
        # ASCII plano se preserva.
        self.assertEqual(_escape_control_chars("plain text-123"), "plain text-123")

    def test_unrecognized_argv_with_cc_exits_two_and_escaped(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.abspath(SRC)
        for cp, label in ((0x85, "NEL"), (0x9B, "CSI"), (0x1B, "ESC"), (0x0D, "CR")):
            arg = "a" + chr(cp) + "b"
            result = subprocess.run(
                [sys.executable, "-m", "epistates", "describe", "--format", "json", arg],
                capture_output=True, env=env,
            )
            self.assertEqual(result.returncode, 2, label)
            self.assertNotIn(arg.encode("utf-8"), result.stderr, label)


# ---------------------------------------------------------------------------
# Proceso real: ASCII encoding, locale/TZ, determinismo.
# ---------------------------------------------------------------------------


class RealProcessTests(unittest.TestCase):
    def _run_module(self, *argv, extra_env=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.abspath(SRC)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "epistates", *argv],
            capture_output=True, env=env,
        )

    def test_describe_under_ascii_no_traceback(self):
        result = self._run_module(
            "describe", "--format", "json",
            extra_env={"PYTHONIOENCODING": "ascii", "LC_ALL": "C", "TZ": "UTC"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        json.loads(result.stdout.decode("utf-8"))

    def test_describe_byte_identical_across_envs(self):
        a = self._run_module("describe", "--format", "json",
                             extra_env={"LC_ALL": "C", "TZ": "UTC"})
        b = self._run_module("describe", "--format", "json",
                             extra_env={"LC_ALL": "en_US.UTF-8", "TZ": "Asia/Tokyo"})
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(a.returncode, 0)

    def test_version_under_ascii(self):
        result = self._run_module(
            "--version",
            extra_env={"PYTHONIOENCODING": "ascii", "LC_ALL": "C", "TZ": "UTC"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), _version.__version__.encode())


if __name__ == "__main__":
    unittest.main()
