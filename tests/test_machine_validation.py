"""H4 Slice2 — validación machine-readable e input hardening.

Cubre el contrato de ``validate --format json`` y del loader seguro:

- Reporte único ``epistates/validation-report/v1`` ASCII-escapado,
  determinista, byte-identico entre ejecuciones, invariante ante locale/TZ y
  con ``stderr`` vacío.
- Exits 0/1/2 y frontera de autoridad siempre ``provenance_verified=false``,
  ``authority_status=external_unverified``, ``authorized_to_execute=false``.
- Endurecimiento de TODA entrada (artefacto, bindings, message-file):
  archivo regular, lectura acotada, anti-TOCTOU, UTF-8 estricto, claves
  duplicadas, NaN/Infinity, profundidad, RecursionError, trailing data.
- Sin subprocess/socket/red/reloj/get_terminal_size durante el modo machine.
- Rutas/argv con C0/DEL/C1/ANSI/Unicode hostil: nunca inyectan terminal ni
  rompen el JSON.
"""

import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from epistates.__main__ import (
    _MAX_JSON_DEPTH,
    _ARTIFACT_MAX_BYTES,
    ValidateError,
    _detect_machine_mode,
    _escape_control_chars,
    _safe_load_json_file,
    _safe_read_regular_file,
    artifact_max_bytes,
    build_validation_report_dict,
    error_taxonomy,
    main,
    max_json_depth,
    render_report_json,
    report_schema,
    report_version,
)
from epistates._version import __version__


FIXTURES = Path(__file__).parent.parent / "fixtures"
SRC = os.path.join(os.path.dirname(__file__), "..", "src")


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


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


def _run_real(*argv, extra_env=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.abspath(SRC)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "epistates", *argv],
        capture_output=True, env=env,
    )


def _write_tmp(tmp_path, name, content):
    path = tmp_path / name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# Detección de modo machine y constantes públicas.
# ---------------------------------------------------------------------------


class MachineModeDetectionTests(unittest.TestCase):
    def test_no_argv_means_no_machine_mode(self):
        # sys.argv[1:] normalmente no incluye --format json.
        saved = sys.argv
        sys.argv = ["epistates"]
        try:
            self.assertFalse(_detect_machine_mode(None))
        finally:
            sys.argv = saved

    def test_describe_format_json_does_not_trigger_machine_mode(self):
        self.assertFalse(_detect_machine_mode(["describe", "--format", "json"]))
        self.assertFalse(_detect_machine_mode(["describe", "--format=json"]))

    def test_validate_format_json_triggers_machine_mode(self):
        self.assertTrue(_detect_machine_mode(["validate", "x.json", "--format", "json"]))
        self.assertTrue(_detect_machine_mode(["validate", "x.json", "--format=json"]))
        self.assertTrue(_detect_machine_mode(["validate", "--format", "json", "x.json"]))

    def test_validate_format_text_does_not_trigger(self):
        self.assertFalse(_detect_machine_mode(["validate", "x.json", "--format", "text"]))
        self.assertFalse(_detect_machine_mode(["validate", "x.json", "--format=text"]))

    def test_duplicate_format_uses_last_complete_value(self):
        self.assertTrue(_detect_machine_mode([
            "validate", "x.json", "--format", "text", "--format", "json",
        ]))
        self.assertFalse(_detect_machine_mode([
            "validate", "x.json", "--format", "json", "--format", "text",
        ]))
        self.assertTrue(_detect_machine_mode([
            "validate", "x.json", "--format", "json", "--format",
        ]))
        self.assertTrue(_detect_machine_mode([
            "validate", "x.json", "--format", "json", "--format", "--bogus",
        ]))

    def test_abbreviation_does_not_trigger(self):
        # allow_abbrev=False en el parser; pre-scan no debe expandir tampoco.
        self.assertFalse(_detect_machine_mode(["validate", "x.json", "--form", "json"]))

    def test_unknown_subcommand_does_not_trigger(self):
        self.assertFalse(_detect_machine_mode(["other", "--format", "json"]))


class PublicConstantsTests(unittest.TestCase):
    def test_report_schema_and_version_stable(self):
        self.assertEqual(report_schema(), "epistates/validation-report/v1")
        self.assertEqual(report_version(), "v1")

    def test_artifact_limit_is_one_mib(self):
        self.assertEqual(artifact_max_bytes(), 1024 * 1024)

    def test_max_json_depth_is_explicit(self):
        self.assertEqual(max_json_depth(), _MAX_JSON_DEPTH)
        self.assertGreater(_MAX_JSON_DEPTH, 0)

    def test_error_taxonomy_is_closed_and_contains_required_codes(self):
        codes = {code for code, _ in error_taxonomy()}
        for required in (
            "file_is_symlink", "file_not_regular", "file_too_large",
            "file_changed_during_read", "invalid_utf8", "invalid_json",
            "duplicate_json_key", "json_too_deep", "recursion_error",
            "schema_missing", "schema_unsupported", "contract_violation",
            "binding_missing", "binding_invalid", "cli_usage_error",
            "json_unsupported_constant",
        ):
            self.assertIn(required, codes, required)
        # Cada code es único y no vacío; cada descripción no vacía.
        codes_list = [c for c, _ in error_taxonomy()]
        self.assertEqual(len(set(codes_list)), len(codes_list))
        for code, desc in error_taxonomy():
            self.assertTrue(code and isinstance(code, str))
            self.assertTrue(desc and isinstance(desc, str))


# ---------------------------------------------------------------------------
# Reporte: éxito, contrato inválido, binding inválido, schema ausente.
# ---------------------------------------------------------------------------


class SuccessReportTests(unittest.TestCase):
    def test_validate_task_card_json_mode(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"), "--format", "json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["schema"], "epistates/validation-report/v1")
        self.assertEqual(report["validation_report_version"], "v1")
        self.assertEqual(report["package_version"], __version__)
        self.assertEqual(
            report["artifact_schema"], "epistates/task-card/v1"
        )
        self.assertEqual(report["provenance_verified"], False)
        self.assertEqual(report["authority_status"], "external_unverified")
        self.assertEqual(report["authorized_to_execute"], False)
        self.assertEqual(report["result"], "valid")
        self.assertEqual(report["exit_code"], 0)
        self.assertIsNone(report["error"])
        self.assertEqual(report["phases"]["load"]["status"], "valid")
        self.assertEqual(report["phases"]["contract"]["status"], "valid")
        # task-card no requiere binding -> not_requested.
        self.assertEqual(report["phases"]["binding"]["status"], "not_requested")

    def test_validate_adapter_capabilities_binding_not_requested(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--format", "json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["phases"]["binding"]["status"], "not_requested")
        self.assertEqual(
            report["artifact_schema"], "epistates/adapter-capabilities/v1"
        )

    def test_validate_audit_result_h2_with_binding(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "audit-result-valid.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--format", "json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["phases"]["binding"]["status"], "valid")
        self.assertEqual(report["artifact_schema"], "epistates/audit-result/v1")

    def test_report_byte_identical_across_runs(self):
        a = _run_cli("validate", str(FIXTURES / "task-card-valid.json"), "--format", "json")[1]
        b = _run_cli("validate", str(FIXTURES / "task-card-valid.json"), "--format", "json")[1]
        self.assertEqual(a, b)

    def test_report_is_single_json_object_with_newline(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"), "--format", "json",
        )
        self.assertTrue(out.endswith("\n"))
        self.assertEqual(out.count("\n"), 1)
        json.loads(out)  # debe parsear limpio


class RealProcessDeterminismTests(unittest.TestCase):
    def test_byte_identical_across_real_processes(self):
        r1 = _run_real("validate", str(FIXTURES / "task-card-valid.json"), "--format", "json")
        r2 = _run_real("validate", str(FIXTURES / "task-card-valid.json"), "--format", "json")
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r1.stderr, b"")
        self.assertEqual(r1.stdout, r2.stdout)

    def test_stable_under_locale_tz_and_ascii_ioencoding(self):
        baseline = _run_real(
            "validate", str(FIXTURES / "task-card-valid.json"), "--format", "json",
            extra_env={"LC_ALL": "C", "TZ": "UTC"},
        ).stdout
        for env in (
            {"LC_ALL": "ja_JP.UTF-8", "TZ": "Asia/Tokyo"},
            {"LC_ALL": "C", "TZ": "America/Buenos_Aires"},
            {"PYTHONIOENCODING": "ascii", "LC_ALL": "C", "TZ": "UTC"},
        ):
            stdout = _run_real(
                "validate", str(FIXTURES / "task-card-valid.json"),
                "--format", "json", extra_env=env,
            ).stdout
            self.assertEqual(stdout, baseline, env)


class ExitCodeTests(unittest.TestCase):
    def test_exit_zero_on_valid_artifact(self):
        self.assertEqual(_run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"), "--format", "json",
        )[0], 0)

    def test_exit_one_on_invalid_contract(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-missing-prohibitions.json"),
            "--format", "json",
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["result"], "invalid")
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["phases"]["load"]["status"], "valid")
        self.assertEqual(report["phases"]["contract"]["status"], "invalid")
        self.assertEqual(report["phases"]["binding"]["status"], "skipped")
        self.assertEqual(report["error"]["code"], "contract_violation")

    def test_exit_one_on_missing_binding_options(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "preflight-result-ok.json"), "--format", "json",
        )
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "binding_missing")
        self.assertEqual(report["phases"]["binding"]["status"], "invalid")
        self.assertEqual(report["phases"]["contract"]["status"], "valid")

    def test_exit_one_on_binding_invalid_inapplicable_option(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
            "--format", "json",
        )
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "binding_invalid")

    def test_exit_two_on_unknown_format_value_goes_to_stderr_text(self):
        # --format yaml es rechazado por argparse ANTES de reconocer modo
        # machine (el valor no es 'json'). El error va a stderr (no JSON),
        # exit 2. Limite documentado del pre-scan argparse-previo.
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--format", "yaml",
        )
        self.assertEqual(code, 2)
        self.assertNotIn("validation-report", out)

    def test_exit_two_on_unknown_flag_in_machine_mode_emits_json(self):
        # --format json SI está presente: el error argparseUnknown va como JSON.
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--format", "json", "--bogus-flag",
        )
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["result"], "invalid")
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["error"]["code"], "cli_usage_error")
        self.assertIsNone(report["artifact_path"])
        for phase in ("load", "contract", "binding"):
            self.assertEqual(report["phases"][phase]["status"], "skipped")

    def test_duplicate_format_then_usage_error_respects_last_value(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--format", "text", "--format", "json", "--bogus-flag",
        )
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["error"]["code"], "cli_usage_error")

        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--format", "json", "--format", "text", "--bogus-flag",
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("unrecognized arguments", err)

    def test_incomplete_final_format_preserves_prior_machine_channel(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--format", "json", "--format", "--bogus-flag",
        )
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["error"]["code"], "cli_usage_error")

    def test_exit_two_on_missing_artifact_in_machine_mode(self):
        # Falta el argumento posicional obligatorio; argparse lo rechaza.
        code, out, err = _run_cli("validate", "--format", "json")
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "cli_usage_error")

    def test_exit_two_on_missing_artifact_in_text_mode_goes_to_stderr(self):
        code, out, err = _run_cli("validate")
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# Reporte: autoridad/provenance SIEMPRE false (incluso si la tarjeta se
# autodeclara authority).
# ---------------------------------------------------------------------------


class AuthorityFrontierTests(unittest.TestCase):
    def test_authority_fields_always_false_on_valid_task_card(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"), "--format", "json",
        )
        report = json.loads(out)
        self.assertFalse(report["provenance_verified"])
        self.assertEqual(report["authority_status"], "external_unverified")
        self.assertFalse(report["authorized_to_execute"])

    def test_authority_fields_false_on_invalid(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-missing-prohibitions.json"),
            "--format", "json",
        )
        report = json.loads(out)
        self.assertFalse(report["provenance_verified"])
        self.assertEqual(report["authority_status"], "external_unverified")
        self.assertFalse(report["authorized_to_execute"])

    def test_audit_result_review_bound_does_not_elevate_authority(self):
        # Audit-result en modo puente (aceptado) sigue sin conceder autoridad.
        argv = [
            "validate", str(FIXTURES / "audit-result-review-bound.json"),
            "--task-card", str(FIXTURES / "task-card-valid.json"),
            "--adapter-capabilities", str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
            "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
            "--dispatch-receipt", str(FIXTURES / "dispatch-receipt-ok.json"),
            "--human-notice", str(FIXTURES / "human-notice-ok.json"),
            "--review-evidence", str(FIXTURES / "review-evidence-ok.json"),
            "--run-id", "run-001", "--attempt-id", "attempt-001",
            "--expected-session-name", "epistates-opencode",
            "--expected-command", "idle",
            "--max-preflight-age-seconds", "600",
            "--max-dispatch-age-seconds", "3600",
            "--max-notice-age-seconds", "3600",
            "--message-file", str(FIXTURES / "dispatch-message.txt"),
            "--expected-classification", "OK",
            "--expected-decision", "proceed",
            "--expected-decision-reference", "conversation-2026-08-11",
            "--expected-observed-at", "2026-08-11T19:00:00Z",
            "--max-audit-age-seconds", "3600",
            "--expected-grant-id", "maintainer-e1-contracts",
            "--expected-grant-digest",
            "sha256:24a39dff4b7a38f45959b89850debed2bb584fb4c887278748064ed6f1eda2cd",
            "--format", "json",
        ]
        code, out, err = _run_cli(*argv)
        self.assertEqual(code, 0, out)
        report = json.loads(out)
        self.assertFalse(report["provenance_verified"])
        self.assertEqual(report["authority_status"], "external_unverified")
        self.assertFalse(report["authorized_to_execute"])


# ---------------------------------------------------------------------------
# Schema ausente / no soportado.
# ---------------------------------------------------------------------------


class SchemaPhaseTests(unittest.TestCase):
    def test_schema_missing(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "no-schema.json", json.dumps({"foo": 1}))
            code, out, err = _run_cli("validate", str(path), "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "schema_missing")
        self.assertIsNone(report["artifact_schema"])
        self.assertEqual(report["phases"]["load"]["status"], "invalid")
        self.assertEqual(report["phases"]["contract"]["status"], "skipped")

    def test_schema_unsupported(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(
                Path(td), "weird.json",
                json.dumps({"schema": "epistates/unknown/v1"}),
            )
            code, out, err = _run_cli("validate", str(path), "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "schema_unsupported")
        self.assertEqual(report["artifact_schema"], "epistates/unknown/v1")

    def test_artifact_not_object(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "array.json", "[1, 2, 3]")
            code, out, err = _run_cli("validate", str(path), "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "schema_missing")


# ---------------------------------------------------------------------------
# Carga segura: tipos de archivo rechazados (sin bloquear).
# ---------------------------------------------------------------------------


class SafeLoaderFileKindTests(unittest.TestCase):
    def test_directory_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            code, out, err = _run_cli("validate", td, "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_not_regular")
        self.assertEqual(report["phases"]["load"]["status"], "invalid")

    def test_fifo_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            fifo = Path(td) / "fifo.json"
            os.mkfifo(fifo)
            code, out, err = _run_cli("validate", str(fifo), "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_not_regular")
        self.assertIn("fifo", report["error"]["details"]["kind"])

    def test_unix_socket_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            sock_path = Path(td) / "sock.json"
            server = socket.socket(socket.AF_UNIX)
            try:
                server.bind(str(sock_path))
                code, out, err = _run_cli(
                    "validate", str(sock_path), "--format", "json",
                )
            finally:
                server.close()
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_not_regular")
        self.assertIn("socket", report["error"]["details"]["kind"])

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target = _write_tmp(
                Path(td), "real.json",
                json.dumps({"schema": "epistates/task-card/v1"}),
            )
            link = Path(td) / "link.json"
            os.symlink(target, link)
            code, out, err = _run_cli("validate", str(link), "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_is_symlink")

    def test_dev_null_rejected_as_not_regular(self):
        # /dev/null es char_device: se rechaza por file_not_regular.
        if not Path("/dev/null").exists():
            self.skipTest("/dev/null no disponible")
        code, out, err = _run_cli("validate", "/dev/null", "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_not_regular")

    def test_missing_path_rejected_with_file_not_found(self):
        code, out, err = _run_cli(
            "validate", "/no/such/file.json", "--format", "json",
        )
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_not_found")


# ---------------------------------------------------------------------------
# Carga segura: lectura acotada y mentira de st_size.
# ---------------------------------------------------------------------------


class BoundedReadTests(unittest.TestCase):
    def test_within_limit_passes(self):
        # Archivo de 1 byte (menor que el límite) -> OK en lectura.
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(
                Path(td), "small.json",
                json.dumps({"schema": "epistates/task-card/v1"}),
            )
            raw = _safe_read_regular_file(path, 1024)
            self.assertGreater(len(raw), 0)

    def test_at_limit_passes(self):
        # Archivo de exactamente `limit` bytes -> OK.
        with tempfile.TemporaryDirectory() as td:
            payload = b"x" * 64
            path = Path(td) / "at"
            path.write_bytes(payload)
            raw = _safe_read_regular_file(path, 64)
            self.assertEqual(raw, payload)

    def test_over_limit_rejected_by_actual_read(self):
        # st_size miente (pequeño) pero el archivo mide limit+1 -> la barrera
        # de lectura acotada (no stat) es la que rechaza.
        with tempfile.TemporaryDirectory() as td:
            payload = b"x" * 65
            path = Path(td) / "over"
            path.write_bytes(payload)
            small = SimpleNamespace(
                st_mode=stat.S_IFREG, st_size=10,
                st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1,
            )
            with patch("os.lstat", return_value=small):
                with self.assertRaises(Exception) as exc:
                    _safe_read_regular_file(path, 64)
            self.assertIn("excede el límite", str(exc.exception))

    def test_st_size_fast_path_rejects_without_open(self):
        # lstat st_size > limit -> rechazo antes de abrir.
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "ok.json", "{}")
            fake = SimpleNamespace(
                st_mode=stat.S_IFREG, st_size=10_000_000,
                st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1,
            )
            opened = []
            real_open = os.open

            def tracking_open(p, *a, **k):
                opened.append(p)
                return real_open(p, *a, **k)

            with patch("os.lstat", return_value=fake), \
                    patch("os.open", side_effect=tracking_open):
                with self.assertRaises(Exception) as exc:
                    _safe_read_regular_file(path, 1024)
            self.assertEqual(opened, [])
            self.assertEqual(exc.exception.code, "file_too_large")

    def test_size_limit_in_machine_mode_reports_file_too_large(self):
        # lstat miente > límite durante el CLI -> el reporte lleva file_too_large.
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "ok.json", "{}")
            fake = SimpleNamespace(
                st_mode=stat.S_IFREG, st_size=_ARTIFACT_MAX_BYTES + 1,
                st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1,
            )
            with patch("os.lstat", return_value=fake):
                code, out, err = _run_cli(
                    "validate", str(path), "--format", "json",
                )
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_too_large")
        self.assertEqual(
            report["error"]["details"]["limit_bytes"], _ARTIFACT_MAX_BYTES
        )


# ---------------------------------------------------------------------------
# Carga segura: cambio ambiguo durante la lectura.
# ---------------------------------------------------------------------------


class TOCTOUSwapTests(unittest.TestCase):
    def _stat(self, mode=stat.S_IFREG, size=10, dev=1, ino=1, mtime=1, ctime=1):
        return SimpleNamespace(
            st_mode=mode, st_size=size,
            st_dev=dev, st_ino=ino, st_mtime_ns=mtime, st_ctime_ns=ctime,
        )

    def test_inode_change_during_read_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "p.json", "x")
            before = self._stat(ino=1)
            after = self._stat(ino=999)  # inodo distinto
            with patch("os.open", return_value=42), \
                    patch("os.fstat", side_effect=[before, after]), \
                    patch("os.read", return_value=b"x"), \
                    patch("os.close"):
                with self.assertRaises(Exception) as exc:
                    _safe_read_regular_file(path, 64)
            self.assertEqual(exc.exception.code, "file_changed_during_read")

    def test_size_change_during_read_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "p.json", "x")
            before = self._stat(size=10)
            after = self._stat(size=99)
            with patch("os.open", return_value=42), \
                    patch("os.fstat", side_effect=[before, after]), \
                    patch("os.read", return_value=b"x"), \
                    patch("os.close"):
                with self.assertRaises(Exception) as exc:
                    _safe_read_regular_file(path, 64)
            self.assertEqual(exc.exception.code, "file_changed_during_read")

    def test_mtime_change_during_read_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "p.json", "x")
            before = self._stat(mtime=10)
            after = self._stat(mtime=99)
            with patch("os.open", return_value=42), \
                    patch("os.fstat", side_effect=[before, after]), \
                    patch("os.read", return_value=b"x"), \
                    patch("os.close"):
                with self.assertRaises(Exception) as exc:
                    _safe_read_regular_file(path, 64)
            self.assertEqual(exc.exception.code, "file_changed_during_read")

    def test_ctime_change_during_read_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "p.json", "x")
            before = self._stat(ctime=10)
            after = self._stat(ctime=99)
            with patch("os.open", return_value=42), \
                    patch("os.fstat", side_effect=[before, after]), \
                    patch("os.read", return_value=b"x"), \
                    patch("os.close"):
                with self.assertRaises(Exception) as exc:
                    _safe_read_regular_file(path, 64)
            self.assertEqual(exc.exception.code, "file_changed_during_read")

    def test_stable_metadata_passes(self):
        # Mismo before/after -> no se rechaza por TOCTOU. os.read devuelve
        # b"hello" una vez y luego EOF (b"") para no colgar el loop.
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(Path(td), "p.json", "hello")
            snapshot = self._stat(size=5)
            with patch("os.open", return_value=42), \
                    patch("os.fstat", side_effect=[snapshot, snapshot]), \
                    patch("os.read", side_effect=[b"hello", b""]), \
                    patch("os.close"):
                raw = _safe_read_regular_file(path, 64)
            self.assertEqual(raw, b"hello")


# ---------------------------------------------------------------------------
# Carga segura: JSON endurecido (UTF-8, dup keys, NaN/Infinity, depth,
# recursion, trailing data).
# ---------------------------------------------------------------------------


class HardenedJSONTests(unittest.TestCase):
    def _expect(self, content, code):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "f.json"
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
            with self.assertRaises(Exception) as exc:
                _safe_load_json_file(path, 1_000_000)
        self.assertEqual(exc.exception.code, code, content)
        return exc.exception

    def test_invalid_utf8_rejected(self):
        self._expect(b'{"a": "\xff\xfe"}', "invalid_utf8")

    def test_trailing_data_rejected(self):
        self._expect(b'{} garbage', "invalid_json")

    def test_duplicate_keys_top_level_rejected(self):
        self._expect(b'{"a": 1, "a": 2}', "duplicate_json_key")

    def test_duplicate_keys_nested_rejected(self):
        self._expect(b'{"x": {"a": 1, "a": 2}}', "duplicate_json_key")

    def test_nan_rejected(self):
        self._expect(b'{"a": NaN}', "json_unsupported_constant")

    def test_infinity_rejected(self):
        self._expect(b'{"a": Infinity}', "json_unsupported_constant")

    def test_negative_infinity_rejected(self):
        self._expect(b'{"a": -Infinity}', "json_unsupported_constant")

    def test_broken_json_rejected(self):
        self._expect(b'{not json}', "invalid_json")

    def test_deep_json_rejected(self):
        # Construye `[[[ ... ]]]` más profundo que _MAX_JSON_DEPTH.
        depth = _MAX_JSON_DEPTH + 5
        deep = "[" * depth + "]" * depth
        exc = self._expect(deep.encode("utf-8"), "json_too_deep")
        self.assertEqual(exc.details["max_depth"], _MAX_JSON_DEPTH)
        self.assertGreater(exc.details["measured_depth"], _MAX_JSON_DEPTH)

    def test_recursion_error_caught_without_traceback(self):
        # Fuerza RecursionError desde el parser: debe clasificarse estable.
        with patch("json.loads", side_effect=RecursionError("simulado")):
            with tempfile.TemporaryDirectory() as td:
                path = _write_tmp(Path(td), "f.json", "{}")
                with self.assertRaises(Exception) as exc:
                    _safe_load_json_file(path, 1_000_000)
        self.assertEqual(exc.exception.code, "recursion_error")

    def test_all_hardening_errors_surface_in_machine_report(self):
        # Una vuelta CLI: el código del reporte coincide con el del loader.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "f.json"
            path.write_bytes(b'{"a": 1, "a": 2}')
            code, out, err = _run_cli("validate", str(path), "--format", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "duplicate_json_key")
        self.assertEqual(report["phases"]["load"]["status"], "invalid")


# ---------------------------------------------------------------------------
# Carga segura: TODOS los archivos de binding pasan por el mismo loader.
# ---------------------------------------------------------------------------


class BindingFilesHardenedTests(unittest.TestCase):
    def test_binding_task_card_fifo_rejected_in_binding_phase(self):
        # El artefacto principal carga OK; un --task-card FIFO se rechaza en
        # binding phase con code=file_not_regular.
        with tempfile.TemporaryDirectory() as td:
            fifo = Path(td) / "fifo.json"
            os.mkfifo(fifo)
            code, out, err = _run_cli(
                "validate", str(FIXTURES / "audit-result-valid.json"),
                "--task-card", str(fifo),
                "--run-id", "run-001", "--attempt-id", "attempt-001",
                "--format", "json",
            )
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["phases"]["load"]["status"], "valid")
        self.assertEqual(report["phases"]["contract"]["status"], "valid")
        self.assertEqual(report["phases"]["binding"]["status"], "invalid")
        self.assertEqual(report["error"]["code"], "file_not_regular")
        self.assertEqual(report["error"]["details"]["path"], str(fifo))

    def test_binding_message_file_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target = _write_tmp(
                Path(td), "msg.txt",
                "ejecuta: nada\n",
            )
            link = Path(td) / "link.txt"
            os.symlink(target, link)
            code, out, err = _run_cli(
                "validate", str(FIXTURES / "dispatch-receipt-ok.json"),
                "--task-card", str(FIXTURES / "task-card-valid.json"),
                "--adapter-capabilities",
                str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
                "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
                "--run-id", "run-001", "--attempt-id", "attempt-001",
                "--expected-session-name", "epistates-opencode",
                "--expected-command", "idle",
                "--max-preflight-age-seconds", "600",
                "--message-file", str(link),
                "--format", "json",
            )
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error"]["code"], "file_is_symlink")

    def test_binding_message_file_invalid_utf8_keeps_specific_code(self):
        with tempfile.TemporaryDirectory() as td:
            message = Path(td) / "invalid-message.txt"
            message.write_bytes(b"literal-\xff")
            code, out, err = _run_cli(
                "validate", str(FIXTURES / "dispatch-receipt-ok.json"),
                "--task-card", str(FIXTURES / "task-card-valid.json"),
                "--adapter-capabilities",
                str(FIXTURES / "adapter-capabilities-opencode-tmux.json"),
                "--preflight-result", str(FIXTURES / "preflight-result-ok.json"),
                "--run-id", "run-001", "--attempt-id", "attempt-001",
                "--expected-session-name", "epistates-opencode",
                "--expected-command", "idle",
                "--max-preflight-age-seconds", "600",
                "--message-file", str(message),
                "--format", "json",
            )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["phases"]["binding"]["status"], "invalid")
        self.assertEqual(report["error"]["code"], "invalid_utf8")
        self.assertEqual(report["error"]["details"]["path"], str(message))


# ---------------------------------------------------------------------------
# Sanitización Cc (C0 + DEL + C1) y paths/argv hostiles.
# ---------------------------------------------------------------------------


class HostileArgvTests(unittest.TestCase):
    def test_escape_control_chars_covers_full_cc(self):
        for cp in (0x00, 0x0A, 0x0D, 0x1B, 0x7F, 0x85, 0x9B, 0x9F):
            self.assertNotIn(chr(cp), _escape_control_chars("a" + chr(cp) + "b"), hex(cp))
        self.assertEqual(_escape_control_chars("plain ascii 123"), "plain ascii 123")

    def test_path_with_lf_in_argv_escaped_in_json(self):
        # argv hostil: nombre con LF (válido en Unix, pero C0). El reporte JSON
        # debe escaparlo y stdout sigue siendo un único JSON ASCII.
        hostile = "/no/such\npath.json"
        code, out, err = _run_cli("validate", hostile, "--format", "json")
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        self.assertEqual(out.count("\n"), 1)
        report = json.loads(out)
        # ensure_ascii convierte el LF en \n en el JSON; no se refleja crudo.
        self.assertNotIn(hostile, out)
        self.assertEqual(report["artifact_path"], hostile)

    def test_path_with_c1_chars_escaped_in_json(self):
        for cp, label in ((0x85, "NEL"), (0x9B, "CSI"), (0x1B, "ESC")):
            hostile = "/no/such" + chr(cp) + "x.json"
            code, out, err = _run_cli("validate", hostile, "--format", "json")
            self.assertEqual(code, 1, label)
            self.assertEqual(err, "", label)
            self.assertEqual(out.count("\n"), 1, label)
            self.assertNotIn(hostile.encode("utf-8"), out.encode("utf-8"), label)

    def test_non_ascii_filename_escaped(self):
        # Path válido con no-ASCII: el reporte debe serializarlo ensure_ascii.
        with tempfile.TemporaryDirectory() as td:
            path = _write_tmp(
                Path(td), "tarjeta-válida.json",
                json.dumps({"schema": "epistates/task-card/v1"}),
            )
            code, out, err = _run_cli("validate", str(path), "--format", "json")
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        report = json.loads(out)
        # stdout es ASCII puro (ensure_ascii); 'válida' aparece como \u00e1.
        self.assertTrue(out.isascii())
        self.assertEqual(report["artifact_path"], str(path))


# ---------------------------------------------------------------------------
# Sin probing durante machine validate: subprocess/socket/reloj/terminal
# bloqueados; el filesystem autorizado es la única I/O.
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
        )

    def test_machine_validate_does_not_probe(self):
        with ExitStack() as stack:
            for patcher in self._patches():
                stack.enter_context(patcher)
            code, out, err = _run_cli(
                "validate", str(FIXTURES / "task-card-valid.json"),
                "--format", "json",
            )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_machine_validate_invalid_artifact_does_not_probe(self):
        with ExitStack() as stack:
            for patcher in self._patches():
                stack.enter_context(patcher)
            code, out, err = _run_cli(
                "validate", str(FIXTURES / "task-card-missing-prohibitions.json"),
                "--format", "json",
            )
        self.assertEqual(code, 1)

    def test_main_module_has_no_subprocess_or_socket_imports(self):
        import ast as _ast
        from epistates import __main__ as m
        source = _inspect_source(m)
        for node in _ast.walk(_ast.parse(source)):
            if isinstance(node, _ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, _ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertFalse(
                    name.startswith(("subprocess", "socket", "urllib")),
                    name,
                )

    def test_real_process_machine_validate_does_not_probe(self):
        # Sustituye subprocess/socket/get_terminal_size en proceso real.
        script = (
            "import subprocess as sp, socket, shutil, os\n"
            "def _boom(*a, **k):\n"
            "    raise AssertionError('startup probe blocked')\n"
            "sp.run = sp.Popen = sp.call = sp.check_output = _boom\n"
            "socket.socket = _boom\n"
            "shutil.get_terminal_size = _boom\n"
            "import importlib\n"
            "importlib.import_module('epistates')\n"
            "from epistates.__main__ import main\n"
            "import sys\n"
            "sys.exit(main(['validate', %r, '--format', 'json']) or 0)\n"
        ) % str(FIXTURES / "task-card-valid.json")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.abspath(SRC)
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        json.loads(result.stdout.decode("utf-8"))


def _inspect_source(module):
    import inspect
    return inspect.getsource(module)


# ---------------------------------------------------------------------------
# Paridad parser <-> discovery <-> docs.
# ---------------------------------------------------------------------------


class ParserDiscoveryDocsParityTests(unittest.TestCase):
    def test_parser_validate_has_format_with_text_default(self):
        from epistates.__main__ import _build_parser
        import argparse
        parser = _build_parser()
        subparsers = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        validate = subparsers.choices["validate"]
        format_action = next(
            a for a in validate._actions if "--format" in a.option_strings
        )
        self.assertEqual(set(format_action.choices), {"text", "json"})
        self.assertEqual(format_action.default, "text")

    def test_discovery_lists_validation_report_schema_as_output(self):
        from epistates.discovery import build_discovery_document, output_schemas
        doc = build_discovery_document()
        self.assertIn(
            "epistates/validation-report/v1",
            doc["capability_planes"]["catalog"]["schemas_output"],
        )
        self.assertIn("epistates/validation-report/v1", output_schemas())
        # No debe aparecer como input validatable.
        self.assertNotIn(
            "epistates/validation-report/v1",
            doc["capability_planes"]["catalog"]["schemas_validatable"],
        )

    def test_discovery_validate_entry_mentions_format_json_and_hardening(self):
        from epistates.discovery import build_discovery_document
        entry = next(
            e for e in build_discovery_document()["capability_planes"]["catalog"]["cli_surface"]
            if e["name"] == "validate"
        )
        desc = entry["description"]
        self.assertIn("--format json", desc)
        self.assertIn("validation-report/v1", desc)
        self.assertIn("loader seguro", desc)

    def test_docs_agent_integration_publishes_taxonomy_and_format(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "docs", "agent-integration.md",
        )
        with open(path, encoding="utf-8") as handle:
            guide = handle.read()
        # Superficie y formato.
        self.assertIn("`validate --format json`", guide)
        self.assertIn("epistates/validation-report/v1", guide)
        # Exits 0/1/2.
        for token in ("`0`", "`1`", "`2`"):
            self.assertIn(token, guide)
        # Taxonomía cerrada.
        for code, _ in error_taxonomy():
            self.assertIn(f"`{code}`", guide, code)

    def test_readme_mentions_format_json_and_report(self):
        path = os.path.join(os.path.dirname(__file__), "..", "README.md")
        with open(path, encoding="utf-8") as handle:
            readme = handle.read()
        self.assertIn("--format json", readme)
        self.assertIn("validation-report/v1", readme)
        self.assertIn("0", readme)
        self.assertIn("external_unverified", readme)

    def test_plan_marks_slice2_implemented_pending_review(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "docs", "plan-inicial.md",
        )
        with open(path, encoding="utf-8") as handle:
            plan = handle.read()
        self.assertIn(
            "Slice2: validación machine-readable", plan
        )
        self.assertIn("implementado; pendiente de revisión adversarial fresca", plan)


# ---------------------------------------------------------------------------
# Text mode conserva compatibilidad (VALID/INVALID).
# ---------------------------------------------------------------------------


class TextModeCompatTests(unittest.TestCase):
    def test_text_mode_valid_output(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
        )
        self.assertEqual(code, 0)
        self.assertIn("VALID", out)

    def test_text_mode_invalid_output(self):
        code, out, err = _run_cli(
            "validate", str(FIXTURES / "task-card-missing-prohibitions.json"),
        )
        self.assertEqual(code, 1)
        self.assertIn("INVALID", out)

    def test_text_mode_default_when_no_format(self):
        # Sin --format el default es text.
        code1, out1, _ = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
        )
        code2, out2, _ = _run_cli(
            "validate", str(FIXTURES / "task-card-valid.json"),
            "--format", "text",
        )
        self.assertEqual((code1, out1), (code2, out2))


# ---------------------------------------------------------------------------
# Reporte builder API público (sin subprocess real).
# ---------------------------------------------------------------------------


class ReportBuilderAPITests(unittest.TestCase):
    def test_build_success_report_structure(self):
        args = SimpleNamespace(card=Path("foo.json"))
        report = build_validation_report_dict(
            args, "epistates/task-card/v1", "not_requested", None,
        )
        rendered = render_report_json(report)
        self.assertTrue(rendered.endswith("\n"))
        self.assertEqual(rendered.count("\n"), 1)
        # ensure_ascii
        rendered.encode("ascii")
        # Estructura canónica.
        for key in (
            "schema", "validation_report_version", "package_version",
            "artifact_path", "artifact_schema", "provenance_verified",
            "authority_status", "authorized_to_execute", "result",
            "exit_code", "error", "phases",
        ):
            self.assertIn(key, report)
        for phase in ("load", "contract", "binding"):
            self.assertIn("status", report["phases"][phase])
            self.assertIn("error", report["phases"][phase])

    def test_build_failure_report_carries_completed_phases(self):
        args = SimpleNamespace(card=Path("foo.json"))
        error = ValidateError(
            "binding", "binding_missing", "audit-result requiere --task-card",
            artifact_schema="epistates/audit-result/v1",
            completed_phases=["load", "contract"],
        )
        report = build_validation_report_dict(args, None, "not_requested", error)
        self.assertEqual(report["phases"]["load"]["status"], "valid")
        self.assertEqual(report["phases"]["contract"]["status"], "valid")
        self.assertEqual(report["phases"]["binding"]["status"], "invalid")
        self.assertEqual(report["phases"]["binding"]["error"]["code"], "binding_missing")
        self.assertEqual(report["exit_code"], 1)

    def test_render_is_deterministic_and_sorted(self):
        args = SimpleNamespace(card=Path("foo.json"))
        report = build_validation_report_dict(
            args, "epistates/task-card/v1", "not_requested", None,
        )
        self.assertEqual(render_report_json(report), render_report_json(report))


if __name__ == "__main__":
    unittest.main()
