import inspect
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from epistates.contracts import ValidationError
from epistates.dispatch import (
    DispatchError,
    IndeterminateDispatchError,
    LiteralDispatcher,
    PartialDispatchError,
    TmuxLiteralDispatcher,
    _MAX_PREFLIGHT_AGE_CEILING,
    _MESSAGE_MAX_BYTES,
    _message_digest,
    _message_length,
    dispatch_literal_opencode_tmux,
    validate_dispatch_receipt,
    validate_dispatch_receipt_binding,
)


FIXTURES = Path(__file__).parent.parent / "fixtures"
DISPATCH_SRC = Path(inspect.getsourcefile(dispatch_literal_opencode_tmux)).read_text(encoding="utf-8")

TASK_ID = "e1-contracts"
SESSION = "epistates-opencode"
COMMAND = "idle"
RUN_ID = "run-001"
ATTEMPT_ID = "attempt-001"
OBSERVED_AT = "2026-08-11T18:00:00Z"
DISPATCHED_AT = "2026-08-11T18:00:00Z"
MAX_AGE = 600
MESSAGE = "Ejecuta el corte H3-Slice3: entrega literal opencode-tmux y detente."


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _task():
    return load("task-card-valid.json")


def _adapter():
    return load("adapter-capabilities-opencode-tmux.json")


def _preflight_ok():
    return load("preflight-result-ok.json")


def _preflight_blocked():
    return load("preflight-result-blocked.json")


class FakeDispatcher:
    """Dispatcher inyectable determinista que registra cada llamada cerrada."""

    def __init__(self, *, literal_error=None, enter_error=None):
        self.calls = []
        self._literal_error = literal_error
        self._enter_error = enter_error

    def send_literal_text(self, session_name, text):
        self.calls.append(("send_literal_text", session_name, text))
        if self._literal_error is not None:
            raise self._literal_error

    def send_enter(self, session_name):
        self.calls.append(("send_enter", session_name, None))
        if self._enter_error is not None:
            raise self._enter_error


def _default_kwargs(**overrides):
    kwargs = dict(
        expected_run_id=RUN_ID,
        expected_attempt_id=ATTEMPT_ID,
        expected_session_name=SESSION,
        expected_command=COMMAND,
        message=MESSAGE,
        dispatched_at=DISPATCHED_AT,
        max_preflight_age_seconds=MAX_AGE,
        current_state="PREPARED",
        dispatcher=FakeDispatcher(),
    )
    kwargs.update(overrides)
    return kwargs


_SENTINEL = object()


def _dispatch(dispatcher=_SENTINEL, **overrides):
    kwargs = _default_kwargs()
    kwargs.update(overrides)
    if dispatcher is not _SENTINEL:
        kwargs["dispatcher"] = dispatcher
    return dispatch_literal_opencode_tmux(_task(), _adapter(), _preflight_ok(), **kwargs)


def _bind(
    receipt=None, preflight=None, message=None,
    expected_max=MAX_AGE, run_id=RUN_ID, attempt_id=ATTEMPT_ID,
    session=SESSION, command=COMMAND,
):
    """Atajo al binding con defaults coherentes con el fixture."""
    if receipt is None:
        receipt = load("dispatch-receipt-ok.json")
    if preflight is None:
        preflight = _preflight_ok()
    if message is None:
        message = MESSAGE
    validate_dispatch_receipt_binding(
        receipt, _task(), _adapter(), preflight,
        run_id, attempt_id, session, command, expected_max, message,
    )


# ---------------------------------------------------------------------------
# Cero llamadas cuando el preflight bloquea o está mal ligado.
# ---------------------------------------------------------------------------


class ZeroCallsBeforeOkPreflightTests(unittest.TestCase):
    def test_blocked_preflight_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError) as exc:
            dispatch_literal_opencode_tmux(
                _task(), _adapter(), _preflight_blocked(),
                **_default_kwargs(dispatcher=dispatcher),
            )
        self.assertIn("ok", str(exc.exception))
        self.assertEqual(dispatcher.calls, [])

    def test_misbound_run_id_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, expected_run_id="run-999")
        self.assertEqual(dispatcher.calls, [])

    def test_misbound_expected_command_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, expected_command="wrong")
        self.assertEqual(dispatcher.calls, [])

    def test_wrong_session_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, expected_session_name="other")
        self.assertEqual(dispatcher.calls, [])

    def test_altered_preflight_digest_is_rejected_by_binding(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["preflight_result_digest"] = (
            "sha256:" + "0" * 63 + "1"
        )
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt)


# ---------------------------------------------------------------------------
# Validaciones pre-efecto: estado, sesión, mensaje, timestamp, dispatcher.
# ---------------------------------------------------------------------------


class PreEffectValidationTests(unittest.TestCase):
    def test_not_prepared_makes_zero_calls(self):
        for bad in ("DISPATCHED", "WAITING_EXTERNAL", "REVIEW_READY", "DONE"):
            dispatcher = FakeDispatcher()
            with self.assertRaises(DispatchError):
                _dispatch(dispatcher=dispatcher, current_state=bad)
            self.assertEqual(dispatcher.calls, [], msg=bad)

    def test_none_dispatcher_makes_zero_calls(self):
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=None)

    def test_bad_session_makes_zero_calls(self):
        for bad in ("a;b", "a b", "a:b", "-lead", "a" * 65):
            dispatcher = FakeDispatcher()
            with self.assertRaises(DispatchError, msg=bad):
                _dispatch(dispatcher=dispatcher, expected_session_name=bad)
            self.assertEqual(dispatcher.calls, [], msg=bad)

    def test_bad_timestamp_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, dispatched_at="2026-08-11 18:00:00Z")
        self.assertEqual(dispatcher.calls, [])

    def test_message_with_nul_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="ok\x00evil")
        self.assertEqual(dispatcher.calls, [])

    def test_message_with_carriage_return_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="line\rmore")
        self.assertEqual(dispatcher.calls, [])

    def test_message_with_tab_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="a\tb")
        self.assertEqual(dispatcher.calls, [])

    def test_message_with_surrogate_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="a\ud800b")
        self.assertEqual(dispatcher.calls, [])

    def test_message_with_del_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="a\x7fb")
        self.assertEqual(dispatcher.calls, [])

    def test_empty_message_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="")
        self.assertEqual(dispatcher.calls, [])

    def test_whitespace_only_message_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="   \n\n")
        self.assertEqual(dispatcher.calls, [])

    def test_oversized_message_makes_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, message="a" * (_MESSAGE_MAX_BYTES + 1))
        self.assertEqual(dispatcher.calls, [])

    def test_multiline_message_with_lf_is_accepted(self):
        dispatcher = FakeDispatcher()
        receipt, _ = _dispatch(dispatcher=dispatcher, message="línea uno\nlínea dos\n")
        self.assertEqual(dispatcher.calls[0][2], "línea uno\nlínea dos\n")
        self.assertEqual(
            receipt["message_length_utf8"],
            len("línea uno\nlínea dos\n".encode("utf-8")),
        )


# ---------------------------------------------------------------------------
# Política de frescura inyectada.
# ---------------------------------------------------------------------------


class FreshnessPolicyTests(unittest.TestCase):
    def test_stale_dispatch_is_rejected_zero_calls(self):
        dispatcher = FakeDispatcher()
        # observed 18:00, dispatched 18:11 (660s) > max 600s.
        with self.assertRaises(DispatchError):
            _dispatch(
                dispatcher=dispatcher,
                dispatched_at="2026-08-11T18:11:00Z",
            )
        self.assertEqual(dispatcher.calls, [])

    def test_dispatched_preceding_observed_is_rejected_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, dispatched_at="2026-08-11T17:00:00Z")
        self.assertEqual(dispatcher.calls, [])

    def test_negative_max_age_rejected_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, max_preflight_age_seconds=-5)
        self.assertEqual(dispatcher.calls, [])

    def test_zero_max_age_rejected_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, max_preflight_age_seconds=0)
        self.assertEqual(dispatcher.calls, [])

    def test_over_ceiling_max_age_rejected_zero_calls(self):
        dispatcher = FakeDispatcher()
        with self.assertRaises(DispatchError):
            _dispatch(
                dispatcher=dispatcher,
                max_preflight_age_seconds=_MAX_PREFLIGHT_AGE_CEILING + 1,
            )
        self.assertEqual(dispatcher.calls, [])

    def test_non_finite_max_age_rejected(self):
        dispatcher = FakeDispatcher()
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(DispatchError, msg=repr(bad)):
                _dispatch(dispatcher=dispatcher, max_preflight_age_seconds=bad)
            self.assertEqual(dispatcher.calls, [], msg=repr(bad))

    def test_exact_boundary_age_is_accepted(self):
        # observed 18:00:00, dispatched 18:10:00 (600s) == max 600s: OK (<=).
        dispatcher = FakeDispatcher()
        receipt, _ = _dispatch(
            dispatcher=dispatcher,
            dispatched_at="2026-08-11T18:10:00Z",
            max_preflight_age_seconds=600,
        )
        self.assertEqual(receipt["final_state"], "WAITING_EXTERNAL")

    def test_future_dispatched_far_ahead_rejected(self):
        dispatcher = FakeDispatcher()
        # Repro (B): observed_at 2026 con dispatched_at 2099.
        with self.assertRaises(DispatchError):
            _dispatch(dispatcher=dispatcher, dispatched_at="2099-01-01T00:00:00Z")
        self.assertEqual(dispatcher.calls, [])

    def test_binding_rejects_stale_receipt(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["dispatched_at"] = "2026-08-11T18:11:00Z"  # 660s > 600 policy
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt)

    def test_auto_amplified_policy_is_rejected(self):
        # Repro (A): mutar dispatched_at a 19:00 y max_age a 3600 no basta: la
        # política externa (600) exige igualdad exacta y re_deriva frescura.
        receipt = load("dispatch-receipt-ok.json")
        receipt["dispatched_at"] = "2026-08-11T19:00:00Z"
        receipt["max_preflight_age_seconds"] = 3600
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt, expected_max=MAX_AGE)

    def test_expected_policy_distinct_from_receipt_is_rejected(self):
        # El recibo dice 600; el controlador espera 599 -> igualdad falla.
        with self.assertRaises(ValidationError):
            _bind(expected_max=599)


# ---------------------------------------------------------------------------
# Éxito: exactamente dos llamadas cerradas, en orden.
# ---------------------------------------------------------------------------


class TwoCallsOrderTests(unittest.TestCase):
    def test_success_makes_exactly_two_calls_in_order(self):
        dispatcher = FakeDispatcher()
        receipt, state = _dispatch(dispatcher=dispatcher)
        self.assertEqual(dispatcher.calls, [
            ("send_literal_text", SESSION, MESSAGE),
            ("send_enter", SESSION, None),
        ])
        self.assertEqual(len(dispatcher.calls), 2)
        self.assertEqual(state, "WAITING_EXTERNAL")
        self.assertEqual(receipt["final_state"], "WAITING_EXTERNAL")

    def test_no_observation_after_enter(self):
        dispatcher = FakeDispatcher()
        _dispatch(dispatcher=dispatcher)
        self.assertEqual(len(dispatcher.calls), 2)


# ---------------------------------------------------------------------------
# Literality: metacaracteres y newlines se preservan como un único argv.
# ---------------------------------------------------------------------------


class LiteralTextTests(unittest.TestCase):
    def test_metacharacters_and_newlines_preserved_verbatim(self):
        message = (
            "sh -c 'rm -rf /';\n"
            "echo $HOME `whoami`\n"
            "| & > /dev/null\n"
            "\"quoted\" 'single'\n"
            "#comment\n"
        )
        dispatcher = FakeDispatcher()
        _dispatch(dispatcher=dispatcher, message=message)
        self.assertEqual(dispatcher.calls[0], ("send_literal_text", SESSION, message))

    def test_message_equals_single_literal_token(self):
        dispatcher = FakeDispatcher()
        message = "line1\nline2 ;; | && $X `y`\nline3"
        _dispatch(dispatcher=dispatcher, message=message)
        self.assertEqual(len(dispatcher.calls), 2)
        self.assertEqual(dispatcher.calls[0][2], message)

    def test_multiline_digest_matches_utf8_bytes(self):
        message = "primera\nsecond line\n"
        receipt, _ = _dispatch(message=message)
        self.assertEqual(receipt["message_digest"], _message_digest(message))
        self.assertEqual(receipt["message_length_utf8"], len(message.encode("utf-8")))


# ---------------------------------------------------------------------------
# Sin reintento: tres categorías (pre-efecto, indeterminada, parcial).
# ---------------------------------------------------------------------------


class NoRetryThreeCategoriesTests(unittest.TestCase):
    def test_phase1_failure_is_indeterminate_not_dispatch(self):
        dispatcher = FakeDispatcher(literal_error=RuntimeError("boom"))
        with self.assertRaises(IndeterminateDispatchError) as exc:
            _dispatch(dispatcher=dispatcher)
        # No es pre-efecto ni parcial: categoría distinta.
        self.assertNotIsInstance(exc.exception, DispatchError)
        self.assertNotIsInstance(exc.exception, PartialDispatchError)
        # Enter nunca se llamó.
        self.assertEqual(len(dispatcher.calls), 1)
        self.assertEqual(dispatcher.calls[0][0], "send_literal_text")

    def test_phase1_subprocess_failure_is_indeterminate(self):
        # El dispatcher de producción lanza IndeterminateDispatchError; la
        # orquestación lo preserva como indeterminado.
        dispatcher = FakeDispatcher(literal_error=IndeterminateDispatchError("exit no cero"))
        with self.assertRaises(IndeterminateDispatchError):
            _dispatch(dispatcher=dispatcher)
        self.assertEqual(len(dispatcher.calls), 1)

    def test_phase2_failure_is_partial_no_retry(self):
        dispatcher = FakeDispatcher(enter_error=RuntimeError("enter boom"))
        with self.assertRaises(PartialDispatchError):
            _dispatch(dispatcher=dispatcher)
        literal_calls = [c for c in dispatcher.calls if c[0] == "send_literal_text"]
        enter_calls = [c for c in dispatcher.calls if c[0] == "send_enter"]
        self.assertEqual(len(literal_calls), 1)
        self.assertEqual(len(enter_calls), 1)

    def test_phase2_partial_error_carries_no_retry_warning(self):
        dispatcher = FakeDispatcher(enter_error=IndeterminateDispatchError("exit no cero"))
        with self.assertRaisesRegex(PartialDispatchError, "NO reintentar"):
            _dispatch(dispatcher=dispatcher)

    def test_indeterminate_error_does_not_duplicate_on_no_retry(self):
        # La función no reintenta: una vez lanzada IndeterminateDispatchError,
        # el literal se intentó una sola vez (no hay segundo intento automático).
        dispatcher = FakeDispatcher(literal_error=IndeterminateDispatchError("timeout"))
        with self.assertRaises(IndeterminateDispatchError):
            _dispatch(dispatcher=dispatcher)
        self.assertEqual(
            [c[0] for c in dispatcher.calls],
            ["send_literal_text"],
        )


# ---------------------------------------------------------------------------
# Recibo sin prompt, ligado al preflight.
# ---------------------------------------------------------------------------


class ReceiptNoPromptTests(unittest.TestCase):
    def test_receipt_has_no_message_field(self):
        receipt, _ = _dispatch()
        self.assertNotIn("message", receipt)
        self.assertNotIn("prompt", receipt)

    def test_receipt_carries_digest_and_length_not_content(self):
        receipt, _ = _dispatch()
        self.assertEqual(receipt["message_digest"], _message_digest(MESSAGE))
        self.assertEqual(receipt["message_length_utf8"], len(MESSAGE.encode("utf-8")))
        rendered = json.dumps(receipt, sort_keys=True)
        self.assertNotIn(MESSAGE, rendered)

    def test_receipt_confirms_transport_only(self):
        receipt, _ = _dispatch()
        self.assertEqual(receipt["confirms"], "technical_transport_only")
        self.assertEqual(receipt["phases_confirmed"], ["send_literal", "send_enter"])
        self.assertEqual(receipt["final_state"], "WAITING_EXTERNAL")

    def test_receipt_links_preflight_and_ids(self):
        receipt, _ = _dispatch()
        from epistates.audit import canonical_digest
        self.assertEqual(receipt["preflight_result_digest"], canonical_digest(_preflight_ok()))
        self.assertEqual(receipt["task_card_digest"], canonical_digest(_task()))
        self.assertEqual(receipt["adapter_digest"], canonical_digest(_adapter()))
        self.assertEqual(receipt["task_id"], TASK_ID)
        self.assertEqual(receipt["run_id"], RUN_ID)
        self.assertEqual(receipt["attempt_id"], ATTEMPT_ID)
        self.assertEqual(receipt["adapter_id"], "opencode-tmux")
        self.assertEqual(receipt["session_name"], SESSION)
        self.assertEqual(receipt["dispatched_at"], DISPATCHED_AT)
        self.assertEqual(receipt["max_preflight_age_seconds"], MAX_AGE)


# ---------------------------------------------------------------------------
# Determinismo, reloj y ausencia de polling.
# ---------------------------------------------------------------------------


class DeterminismAndClockTests(unittest.TestCase):
    def test_same_inputs_same_receipt(self):
        r1, _ = _dispatch()
        r2, _ = _dispatch()
        self.assertEqual(r1, r2)

    def test_injected_timestamp_affects_receipt(self):
        r1, _ = _dispatch(dispatched_at="2026-08-11T18:00:00Z")
        r2, _ = _dispatch(dispatched_at="2026-08-11T18:05:00Z")
        self.assertNotEqual(r1, r2)

    def test_source_reads_no_clock(self):
        self.assertNotIn("datetime.now", DISPATCH_SRC)
        self.assertNotIn("datetime.utcnow", DISPATCH_SRC)
        self.assertNotIn("time.time", DISPATCH_SRC)
        self.assertNotIn("time.sleep", DISPATCH_SRC)

    def test_only_send_keys_subcommand_is_built(self):
        recorder = _Recorder()
        with patch("epistates.dispatch.subprocess.run", side_effect=recorder):
            dispatcher = TmuxLiteralDispatcher("/usr/bin/tmux", 5, 4096)
            dispatcher.send_literal_text("s", "msg")
            dispatcher.send_enter("s")
        for call in recorder.calls:
            argv = call[0][0]
            self.assertEqual(argv[1], "send-keys", argv)


# ---------------------------------------------------------------------------
# API cerrada.
# ---------------------------------------------------------------------------


class ClosedApiTests(unittest.TestCase):
    def test_orchestration_signature_has_no_argv_or_shell(self):
        params = inspect.signature(dispatch_literal_opencode_tmux).parameters
        for forbidden in ("argv", "cmd", "command", "shell", "script", "args"):
            self.assertNotIn(forbidden, params, forbidden)

    def test_protocol_declares_only_two_closed_operations(self):
        public = {
            name for name in dir(LiteralDispatcher)
            if not name.startswith("_") and callable(getattr(LiteralDispatcher, name))
        }
        self.assertEqual(public, {"send_literal_text", "send_enter"})

    def test_dispatcher_methods_take_no_argv(self):
        params = inspect.signature(TmuxLiteralDispatcher.send_literal_text).parameters
        self.assertEqual(list(params), ["self", "session_name", "text"])
        params = inspect.signature(TmuxLiteralDispatcher.send_enter).parameters
        self.assertEqual(list(params), ["self", "session_name"])

    def test_production_public_api_is_only_two_methods(self):
        public = {
            name for name in dir(TmuxLiteralDispatcher)
            if not name.startswith("_") and callable(getattr(TmuxLiteralDispatcher, name))
        }
        self.assertEqual(public, {"send_literal_text", "send_enter"})

    def test_no_post_effect_computation(self):
        # Tras Enter no debe quedar canonicalización, validación ni transición
        # capaces de lanzar: todo se precalculó antes del primer send.
        src = inspect.getsource(dispatch_literal_opencode_tmux)
        tail = src.split("dispatcher.send_enter(session)", 1)[1]
        for forbidden in (
            "canonical_digest", "transition", "_message_digest", "_message_length",
            "validate_", "_validate_", "_parse_utc", "_coerce_session", "_require_",
        ):
            self.assertNotIn(forbidden, tail, forbidden)


# ---------------------------------------------------------------------------
# Production TmuxLiteralDispatcher: disciplina subprocess y fail-closed.
# ---------------------------------------------------------------------------


TMUX = "/usr/bin/tmux"


def _completed(stdout=b"", stderr=b"", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class _Recorder:
    def __init__(self, returns=None, side_effect=None):
        self.calls = []
        self._returns = list(returns or [])
        self._side_effect = side_effect
        self._index = 0

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._side_effect is not None:
            raise self._side_effect
        if self._index < len(self._returns):
            value = self._returns[self._index]
            self._index += 1
            return value
        return _completed()


class TmuxDispatcherSubprocessTests(unittest.TestCase):
    def setUp(self):
        self.recorder = _Recorder()
        self.patcher = patch("epistates.dispatch.subprocess.run", side_effect=self.recorder)
        self.mock = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _dispatcher(self, **overrides):
        kwargs = dict(tmux_path=TMUX, timeout_seconds=5, max_output_bytes=4096)
        kwargs.update(overrides)
        return TmuxLiteralDispatcher(**kwargs)

    def _last_argv(self):
        return self.recorder.calls[-1][0][0]

    def _last_kwargs(self):
        return self.recorder.calls[-1][1]

    def test_send_literal_text_argv_uses_literal_flag_and_terminator(self):
        dispatcher = self._dispatcher()
        dispatcher.send_literal_text("epistates-opencode", "echo hi\n;; | $X")
        self.assertEqual(self._last_argv(), [
            TMUX, "send-keys", "-l", "-t", "epistates-opencode", "--", "echo hi\n;; | $X",
        ])

    def test_send_literal_text_terminator_before_message_starting_with_dash(self):
        # Un mensaje que empieza en ``-`` no se parsea como flag: ``--`` lo separa.
        dispatcher = self._dispatcher()
        dispatcher.send_literal_text("s", "-rf / --evil")
        argv = self._last_argv()
        self.assertEqual(argv, [TMUX, "send-keys", "-l", "-t", "s", "--", "-rf / --evil"])
        self.assertEqual(argv[-1], "-rf / --evil")
        self.assertIn("--", argv)

    def test_send_enter_argv_has_no_literal_flag(self):
        dispatcher = self._dispatcher()
        dispatcher.send_enter("epistates-opencode")
        self.assertEqual(self._last_argv(), [
            TMUX, "send-keys", "-t", "epistates-opencode", "Enter",
        ])
        self.assertNotIn("-l", self._last_argv())

    def test_subprocess_discipline_no_shell(self):
        dispatcher = self._dispatcher()
        dispatcher.send_literal_text("epistates-opencode", "msg")
        kwargs = self._last_kwargs()
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)
        self.assertIsNone(kwargs["cwd"])
        self.assertEqual(kwargs["timeout"], 5)
        self.assertIs(kwargs["check"], False)
        self.assertNotIn("text", kwargs)
        self.assertNotIn("encoding", kwargs)

    def test_env_is_minimal_and_excludes_hostile_keys(self):
        dispatcher = self._dispatcher()
        dispatcher.send_enter("epistates-opencode")
        env = self._last_kwargs()["env"]
        self.assertEqual(env, {"LC_ALL": "C", "LANG": "C"})
        for forbidden in ("HOME", "PATH", "TMUX", "TMUX_TMPDIR", "GIT_DIR", "TERM"):
            self.assertNotIn(forbidden, env, forbidden)

    def test_env_does_not_inherit_hostile_process_env(self):
        import os
        hostile = {"TMUX": "/tmp/x", "TMUX_TMPDIR": "/evil", "HOME": "/evil", "PATH": "/evil/bin"}
        dispatcher = self._dispatcher()
        with patch.dict(os.environ, hostile, clear=False):
            dispatcher.send_enter("epistates-opencode")
        env = self._last_kwargs()["env"]
        for key in hostile:
            self.assertNotIn(key, env, key)

    def test_metacharacters_preserved_as_single_argv_element(self):
        dispatcher = self._dispatcher()
        message = "a; b | c && d `e` $f \"g\" 'h'\nnewline"
        dispatcher.send_literal_text("s", message)
        argv = self._last_argv()
        self.assertEqual(argv[-1], message)
        self.assertEqual(argv.count(message), 1)

    def test_constructor_rejects_relative_executable(self):
        with self.assertRaises(DispatchError):
            self._dispatcher(tmux_path="tmux")

    def test_constructor_rejects_bad_timeout(self):
        for bad in (0, -1, True, None, "5", float("nan"), float("inf"), 61):
            with self.assertRaises(DispatchError, msg=repr(bad)):
                self._dispatcher(timeout_seconds=bad)

    def test_constructor_rejects_bad_max_output(self):
        for bad in (0, -1, True, None, "5", 17 * 1024 * 1024):
            with self.assertRaises(DispatchError, msg=repr(bad)):
                self._dispatcher(max_output_bytes=bad)

    def test_validates_session_before_subprocess(self):
        dispatcher = self._dispatcher()
        for bad in ("a;b", "a b", "a/b", "a:b", "a.b", "", "a\nb", "-leading"):
            with self.assertRaises(DispatchError, msg=bad):
                dispatcher.send_literal_text(bad, "x")
            with self.assertRaises(DispatchError, msg=bad):
                dispatcher.send_enter(bad)
        self.assertEqual(self.mock.call_count, 0)

    def test_direct_use_validates_message_before_subprocess(self):
        # Requisito: el dispatcher público aplica validación completa aun en
        # uso directo. Mensaje vacío/CR/TAB se rechazan sin llamar a subprocess.
        dispatcher = self._dispatcher()
        for bad in ("", "a\rb", "a\tb", "a\x00b"):
            with self.assertRaises(DispatchError, msg=repr(bad)):
                dispatcher.send_literal_text("s", bad)
        self.assertEqual(self.mock.call_count, 0)

    def test_send_literal_text_rejects_non_str_text(self):
        dispatcher = self._dispatcher()
        with self.assertRaises(DispatchError):
            dispatcher.send_literal_text("s", 123)
        self.assertEqual(self.mock.call_count, 0)

    def test_timeout_is_indeterminate_without_leak(self):
        self.recorder._side_effect = subprocess.TimeoutExpired(cmd=["tmux"], timeout=5)
        dispatcher = self._dispatcher()
        with self.assertRaises(IndeterminateDispatchError) as exc:
            dispatcher.send_enter("s")
        self.assertNotIsInstance(exc.exception, DispatchError)

    def test_missing_executable_is_indeterminate(self):
        self.recorder._side_effect = FileNotFoundError(2, "No such file")
        dispatcher = self._dispatcher()
        with self.assertRaises(IndeterminateDispatchError):
            dispatcher.send_enter("s")

    def test_nonzero_exit_is_indeterminate_without_leak(self):
        secret = "TOPSECRET-stderr"
        self.recorder._returns = [_completed(stderr=secret.encode(), returncode=1)]
        dispatcher = self._dispatcher()
        with self.assertRaises(IndeterminateDispatchError) as exc:
            dispatcher.send_enter("s")
        self.assertNotIn(secret, str(exc.exception))

    def test_stderr_nonempty_is_indeterminate(self):
        self.recorder._returns = [_completed(stdout=b"", stderr=b"warn", returncode=0)]
        dispatcher = self._dispatcher()
        with self.assertRaises(IndeterminateDispatchError):
            dispatcher.send_enter("s")

    def test_unexpected_stdout_is_indeterminate(self):
        self.recorder._returns = [_completed(stdout=b"x", stderr=b"", returncode=0)]
        dispatcher = self._dispatcher()
        with self.assertRaises(IndeterminateDispatchError):
            dispatcher.send_enter("s")

    def test_overflow_is_indeterminate_without_leak(self):
        self.recorder._returns = [_completed(stdout=b"X" * 5000, stderr=b"")]
        dispatcher = self._dispatcher(max_output_bytes=4096)
        with self.assertRaises(IndeterminateDispatchError) as exc:
            dispatcher.send_enter("s")
        self.assertNotIn("X" * 100, str(exc.exception))

    def test_permission_error_is_indeterminate_without_leak(self):
        self.recorder._side_effect = PermissionError(13, "Permission denied: /secret")
        dispatcher = self._dispatcher()
        with self.assertRaises(IndeterminateDispatchError) as exc:
            dispatcher.send_enter("s")
        self.assertNotIn("secret", str(exc.exception))


# ---------------------------------------------------------------------------
# Recibo: validación estructural y binding (con preflight exacto).
# ---------------------------------------------------------------------------


class ReceiptValidatorTests(unittest.TestCase):
    def _message(self):
        return (FIXTURES / "dispatch-message.txt").read_bytes().decode("utf-8")

    def test_fixture_receipt_is_valid(self):
        validate_dispatch_receipt(load("dispatch-receipt-ok.json"))

    def test_fixture_receipt_binds_with_preflight_and_message(self):
        _bind(message=self._message())

    def test_unknown_field_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["extra"] = 1
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_missing_field_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        del receipt["preflight_result_digest"]
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_message_length_zero_fails_structural(self):
        # Requisito: length estructural mínimo 1.
        receipt = load("dispatch-receipt-ok.json")
        receipt["message_length_utf8"] = 0
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_max_age_out_of_range_fails_structural(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["max_preflight_age_seconds"] = _MAX_PREFLIGHT_AGE_CEILING + 1
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_max_age_non_positive_fails_structural(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["max_preflight_age_seconds"] = 0
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_wrong_phases_order_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["phases_confirmed"] = ["send_enter", "send_literal"]
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_wrong_final_state_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["final_state"] = "DISPATCHED"
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_wrong_confirms_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["confirms"] = "agent_understood"
        with self.assertRaises(ValidationError):
            validate_dispatch_receipt(receipt)

    def test_binding_rejects_empty_message(self):
        # El binding no puede aceptar message="" aunque el digest sea el del
        # mensaje vacío: _validate_message lo prohíbe (longitud mínima 1).
        receipt = load("dispatch-receipt-ok.json")
        receipt["message_digest"] = _message_digest("")
        receipt["message_length_utf8"] = 0
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt, message="")

    def test_binding_wrong_preflight_digest_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["preflight_result_digest"] = "sha256:" + "f" * 64
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt, message=self._message())

    def test_binding_wrong_preflight_outcome_fails(self):
        with self.assertRaises(ValidationError):
            _bind(preflight=_preflight_blocked(), message=self._message())

    def test_binding_wrong_message_digest_fails(self):
        with self.assertRaises(ValidationError):
            _bind(message="mensaje distinto")

    def test_binding_wrong_session_fails(self):
        with self.assertRaises(ValidationError):
            _bind(session="otra-sesion", message=self._message())

    def test_binding_wrong_command_fails(self):
        with self.assertRaises(ValidationError):
            _bind(command="wrong", message=self._message())

    def test_binding_future_dispatched_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["dispatched_at"] = "2099-01-01T00:00:00Z"
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt, message=self._message())

    def test_binding_dispatched_preceding_observed_fails(self):
        receipt = load("dispatch-receipt-ok.json")
        receipt["dispatched_at"] = "2026-08-11T17:00:00Z"
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt, message=self._message())

    def test_binding_auto_amplified_policy_fails(self):
        # Repro (A): mutar dispatched_at y max_age a 3600 no basta: la política
        # externa (600) exige igualdad exacta.
        receipt = load("dispatch-receipt-ok.json")
        receipt["dispatched_at"] = "2026-08-11T19:00:00Z"
        receipt["max_preflight_age_seconds"] = 3600
        with self.assertRaises(ValidationError):
            _bind(receipt=receipt, message=self._message())

    def test_binding_expected_policy_distinct_fails(self):
        # El recibo dice 600; el controlador espera 599 -> rechazo.
        with self.assertRaises(ValidationError):
            _bind(expected_max=599, message=self._message())

    def test_binding_external_policy_rederives_freshness(self):
        # Incluso con igualdad exacta a 3600, un dispatched 1h después de
        # observed (3600s) está en el límite y se acepta: la política externa
        # manda, no la auto-amplificación del recibo.
        receipt = load("dispatch-receipt-ok.json")
        receipt["dispatched_at"] = "2026-08-11T19:00:00Z"
        receipt["max_preflight_age_seconds"] = 3600
        _bind(receipt=receipt, expected_max=3600, message=self._message())

    def test_built_receipt_roundtrips_through_binding(self):
        dispatcher = FakeDispatcher()
        receipt, _ = _dispatch(dispatcher=dispatcher)
        _bind(receipt=receipt, message=MESSAGE)


if __name__ == "__main__":
    unittest.main()
