import inspect
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from epistates.review_runner import (
    CaptureOutcome,
    CheckOutcome,
    IndeterminateReviewError,
    ReviewRunner,
    ReviewRunnerError,
    TmuxReviewRunner,
    _CHECK_CATALOG,
)


RUNNER_SRC = Path(inspect.getsourcefile(TmuxReviewRunner)).read_text(encoding="utf-8")

TMUX = "/usr/bin/tmux"
GIT = "/usr/bin/git"
PYTHON = "/usr/bin/python3"
WORKTREE = "/workspace/epistates"


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


# ---------------------------------------------------------------------------
# Catálogo cerrado y API.
# ---------------------------------------------------------------------------


class ClosedCatalogTests(unittest.TestCase):
    def test_check_catalog_is_closed(self):
        self.assertEqual(_CHECK_CATALOG, frozenset({"git_status", "diff_check", "unit_tests"}))

    def test_protocol_declares_only_two_closed_operations(self):
        public = {
            name for name in dir(ReviewRunner)
            if not name.startswith("_") and callable(getattr(ReviewRunner, name))
        }
        self.assertEqual(public, {"capture_once", "run_check"})

    def test_runner_methods_take_no_argv(self):
        params = inspect.signature(TmuxReviewRunner.capture_once).parameters
        self.assertEqual(list(params), ["self", "session_name"])
        params = inspect.signature(TmuxReviewRunner.run_check).parameters
        self.assertEqual(list(params), ["self", "check_id"])

    def test_production_public_api_is_only_two_methods(self):
        public = {
            name for name in dir(TmuxReviewRunner)
            if not name.startswith("_") and callable(getattr(TmuxReviewRunner, name))
        }
        self.assertEqual(public, {"capture_once", "run_check"})


# ---------------------------------------------------------------------------
# Constructor: validación de configuración.
# ---------------------------------------------------------------------------


class ConstructorTests(unittest.TestCase):
    def _runner(self, **overrides):
        kwargs = dict(
            tmux_path=TMUX, git_path=GIT, python_path=PYTHON, worktree=WORKTREE,
            timeout_seconds=5, max_output_bytes=4096, capture_lines=50,
        )
        kwargs.update(overrides)
        return TmuxReviewRunner(**kwargs)

    def test_rejects_relative_tmux(self):
        with self.assertRaises(ReviewRunnerError):
            self._runner(tmux_path="tmux")

    def test_rejects_relative_git(self):
        with self.assertRaises(ReviewRunnerError):
            self._runner(git_path="git")

    def test_rejects_relative_python(self):
        with self.assertRaises(ReviewRunnerError):
            self._runner(python_path="python3")

    def test_rejects_bad_worktree(self):
        for bad in ("relative/path", "/", "../etc", "/a/../b"):
            with self.assertRaises(ReviewRunnerError, msg=bad):
                self._runner(worktree=bad)

    def test_rejects_bad_timeout(self):
        for bad in (0, -1, True, None, "5", float("nan"), float("inf"), 61):
            with self.assertRaises(ReviewRunnerError, msg=repr(bad)):
                self._runner(timeout_seconds=bad)

    def test_rejects_bad_max_output(self):
        for bad in (0, -1, True, None, "5", 17 * 1024 * 1024):
            with self.assertRaises(ReviewRunnerError, msg=repr(bad)):
                self._runner(max_output_bytes=bad)

    def test_rejects_bad_capture_lines(self):
        for bad in (0, -1, True, None, "5", 201):
            with self.assertRaises(ReviewRunnerError, msg=repr(bad)):
                self._runner(capture_lines=bad)

    def test_rejects_unknown_check_id(self):
        runner = self._runner()
        for bad in ("agent_says_ok", "", "argv", "-rf", None):
            with self.assertRaises(ReviewRunnerError, msg=repr(bad)):
                runner.run_check(bad)


# ---------------------------------------------------------------------------
# capture-pane: exactamente una llamada, argv cerrado, disciplina subprocess.
# ---------------------------------------------------------------------------


class CaptureOnceTests(unittest.TestCase):
    def setUp(self):
        self.recorder = _Recorder()
        self.patcher = patch("epistates.review_runner.subprocess.run", side_effect=self.recorder)
        self.mock = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _runner(self, **overrides):
        kwargs = dict(
            tmux_path=TMUX, git_path=GIT, python_path=PYTHON, worktree=WORKTREE,
            timeout_seconds=5, max_output_bytes=4096, capture_lines=50,
        )
        kwargs.update(overrides)
        return TmuxReviewRunner(**kwargs)

    def _last_argv(self):
        return self.recorder.calls[-1][0][0]

    def _last_kwargs(self):
        return self.recorder.calls[-1][1]

    def test_capture_uses_capture_pane_subcommand(self):
        runner = self._runner()
        outcome = runner.capture_once("epistates-opencode")
        argv = self._last_argv()
        self.assertEqual(argv[0], TMUX)
        self.assertEqual(argv[1], "capture-pane")
        self.assertIn("-p", argv)
        self.assertIn("-J", argv)  # join explícito de líneas envueltas.
        self.assertIn("-S", argv)
        self.assertEqual(argv[argv.index("-S") + 1], "-50")
        self.assertEqual(argv[argv.index("-t") + 1], "epistates-opencode")

    def test_capture_returns_metadata_not_content(self):
        runner = self._runner()
        self.recorder._returns = [_completed(stdout=b"linea uno\nlinea dos\n")]
        outcome = runner.capture_once("s")
        self.assertIsInstance(outcome, CaptureOutcome)
        self.assertEqual(outcome.capture_lines, 50)
        self.assertEqual(outcome.length_utf8, len(b"linea uno\nlinea dos\n"))
        self.assertTrue(outcome.digest.startswith("sha256:"))
        # El contenido no sale: sólo digest + longitud.
        rendered = repr(outcome)
        self.assertNotIn("linea uno", rendered)

    def test_capture_subprocess_discipline(self):
        runner = self._runner()
        runner.capture_once("s")
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

    def test_capture_env_is_minimal(self):
        runner = self._runner()
        runner.capture_once("s")
        env = self._last_kwargs()["env"]
        self.assertEqual(env, {"LC_ALL": "C", "LANG": "C", "TMPDIR": "/tmp"})
        for forbidden in ("HOME", "PATH", "TMUX", "TMUX_TMPDIR", "GIT_DIR", "TERM"):
            self.assertNotIn(forbidden, env, forbidden)

    def test_capture_env_does_not_inherit_hostile(self):
        import os
        hostile = {"TMUX": "/tmp/x", "HOME": "/evil", "PATH": "/evil/bin"}
        runner = self._runner()
        with patch.dict(os.environ, hostile, clear=False):
            runner.capture_once("s")
        env = self._last_kwargs()["env"]
        for key in hostile:
            self.assertNotIn(key, env, key)

    def test_capture_validates_session_before_subprocess(self):
        runner = self._runner()
        for bad in ("a;b", "a b", "a:b", "", "-lead"):
            with self.assertRaises(ReviewRunnerError, msg=bad):
                runner.capture_once(bad)
        self.assertEqual(self.mock.call_count, 0)

    def test_capture_timeout_is_indeterminate_no_leak(self):
        self.recorder._side_effect = subprocess.TimeoutExpired(cmd=["tmux"], timeout=5)
        runner = self._runner()
        with self.assertRaises(IndeterminateReviewError) as exc:
            runner.capture_once("s")
        self.assertNotIn("tmux", str(exc.exception).lower())

    def test_capture_missing_executable_is_indeterminate(self):
        self.recorder._side_effect = FileNotFoundError(2, "No such file")
        runner = self._runner()
        with self.assertRaises(IndeterminateReviewError):
            runner.capture_once("s")

    def test_capture_nonzero_exit_is_indeterminate(self):
        self.recorder._returns = [_completed(returncode=1)]
        runner = self._runner()
        with self.assertRaises(IndeterminateReviewError):
            runner.capture_once("s")

    def test_capture_stderr_nonempty_is_indeterminate(self):
        self.recorder._returns = [_completed(stderr=b"warn")]
        runner = self._runner()
        with self.assertRaises(IndeterminateReviewError):
            runner.capture_once("s")

    def test_capture_overflow_is_indeterminate_no_leak(self):
        secret = "X" * 5000
        self.recorder._returns = [_completed(stdout=secret.encode())]
        runner = self._runner(max_output_bytes=4096)
        with self.assertRaises(IndeterminateReviewError) as exc:
            runner.capture_once("s")
        self.assertNotIn(secret[:100], str(exc.exception))

    def test_capture_nul_is_indeterminate(self):
        self.recorder._returns = [_completed(stdout=b"a\x00b")]
        runner = self._runner()
        with self.assertRaises(IndeterminateReviewError):
            runner.capture_once("s")

    def test_capture_invalid_utf8_is_indeterminate(self):
        self.recorder._returns = [_completed(stdout=b"\xff\xfe")]
        runner = self._runner()
        with self.assertRaises(IndeterminateReviewError):
            runner.capture_once("s")


# ---------------------------------------------------------------------------
# Checks: catálogo cerrado, pass/fail por exit code, argv interno.
# ---------------------------------------------------------------------------


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.recorder = _Recorder()
        self.patcher = patch("epistates.review_runner.subprocess.run", side_effect=self.recorder)
        self.mock = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _runner(self, **overrides):
        kwargs = dict(
            tmux_path=TMUX, git_path=GIT, python_path=PYTHON, worktree=WORKTREE,
            timeout_seconds=5, max_output_bytes=4096, capture_lines=50,
        )
        kwargs.update(overrides)
        return TmuxReviewRunner(**kwargs)

    def _last_argv(self):
        return self.recorder.calls[-1][0][0]

    def _last_kwargs(self):
        return self.recorder.calls[-1][1]

    def test_git_status_uses_porcelain_argv(self):
        runner = self._runner()
        outcome = runner.run_check("git_status")
        argv = self._last_argv()
        self.assertEqual(argv[0], GIT)
        # -c core.fsmonitor=false antes del subcomando.
        self.assertEqual(argv[1:4], ["-c", "core.fsmonitor=false", "status"])
        self.assertIn("--porcelain=v1", argv)
        self.assertIn("--", argv)  # terminador.
        self.assertEqual(self._last_kwargs()["cwd"], WORKTREE)

    def test_git_status_pass_when_clean(self):
        runner = self._runner()
        self.recorder._returns = [_completed(stdout=b"")]
        outcome = runner.run_check("git_status")
        self.assertEqual(outcome.status, "pass")
        self.assertEqual(outcome.length_utf8, 0)

    def test_git_status_pass_when_dirty_evidence_in_digest(self):
        runner = self._runner()
        self.recorder._returns = [_completed(stdout=b" M src/foo.py\n")]
        outcome = runner.run_check("git_status")
        # git_status pass = exit 0 (evidencia); el contenido queda en digest.
        self.assertEqual(outcome.status, "pass")
        self.assertEqual(outcome.length_utf8, len(b" M src/foo.py\n"))
        self.assertNotIn("foo.py", repr(outcome))

    def test_diff_check_pass_on_exit_zero(self):
        runner = self._runner()
        outcome = runner.run_check("diff_check")
        argv = self._last_argv()
        # -c core.fsmonitor=false antes del subcomando.
        self.assertEqual(argv[1:4], ["-c", "core.fsmonitor=false", "diff"])
        self.assertIn("--check", argv)
        self.assertIn("--no-ext-diff", argv)
        self.assertIn("HEAD", argv)
        self.assertIn("--", argv)
        self.assertEqual(argv[-1], "--")
        self.assertEqual(outcome.status, "pass")

    def test_diff_check_fail_on_exit_one(self):
        runner = self._runner()
        self.recorder._returns = [_completed(stdout=b"foo.py:1: trailing whitespace\n", returncode=1)]
        outcome = runner.run_check("diff_check")
        self.assertEqual(outcome.status, "fail")
        self.assertNotIn("foo.py", repr(outcome))

    def test_diff_check_indeterminate_on_unexpected_exit(self):
        runner = self._runner()
        self.recorder._returns = [_completed(returncode=2)]
        with self.assertRaises(IndeterminateReviewError):
            runner.run_check("diff_check")

    def test_unit_tests_pass_on_exit_zero(self):
        runner = self._runner()
        self.recorder._returns = [_completed(stdout=b"", stderr=b"Ran 5 tests\nOK\n")]
        outcome = runner.run_check("unit_tests")
        argv = self._last_argv()
        self.assertEqual(argv[0], PYTHON)
        self.assertEqual(argv[1], "-m")
        self.assertEqual(outcome.status, "pass")
        self.assertEqual(outcome.length_utf8, len(b"Ran 5 tests\nOK\n"))

    def test_unit_tests_fail_on_nonzero_exit(self):
        runner = self._runner()
        self.recorder._returns = [_completed(stderr=b"FAILED\n", returncode=1)]
        outcome = runner.run_check("unit_tests")
        self.assertEqual(outcome.status, "fail")

    def test_unit_tests_indeterminate_on_timeout(self):
        runner = self._runner()
        self.recorder._side_effect = subprocess.TimeoutExpired(cmd=[], timeout=5)
        with self.assertRaises(IndeterminateReviewError):
            runner.run_check("unit_tests")

    def test_check_timeout_is_indeterminate_no_leak(self):
        runner = self._runner()
        self.recorder._side_effect = subprocess.TimeoutExpired(cmd=[], timeout=5)
        with self.assertRaises(IndeterminateReviewError):
            runner.run_check("git_status")

    def test_check_overflow_is_indeterminate_no_leak(self):
        runner = self._runner()
        secret = "Y" * 5000
        self.recorder._returns = [_completed(stdout=secret.encode())]
        with self.assertRaises(IndeterminateReviewError) as exc:
            runner.run_check("git_status")
        self.assertNotIn(secret[:100], str(exc.exception))

    def test_git_check_env_excludes_hostile(self):
        import os
        hostile = {"HOME": "/evil", "PATH": "/evil", "GIT_DIR": "/evil"}
        runner = self._runner()
        with patch.dict(os.environ, hostile, clear=False):
            runner.run_check("git_status")
        env = self._last_kwargs()["env"]
        for key in hostile:
            self.assertNotIn(key, env, key)

    def test_git_check_env_has_readonly_git_flags(self):
        runner = self._runner()
        runner.run_check("git_status")
        env = self._last_kwargs()["env"]
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(env["TMPDIR"], "/tmp")

    def test_unit_tests_env_binds_worktree_src(self):
        runner = self._runner()
        runner.run_check("unit_tests")
        env = self._last_kwargs()["env"]
        self.assertEqual(env["PYTHONPATH"], WORKTREE + "/src")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["TMPDIR"], "/tmp")
        # Sin PATH/HOME del caller.
        for forbidden in ("HOME", "PATH", "TMUX", "TMUX_TMPDIR"):
            self.assertNotIn(forbidden, env, forbidden)

    def test_unit_tests_env_does_not_inherit_hostile_pythonpath(self):
        import os
        runner = self._runner()
        with patch.dict(os.environ, {"PYTHONPATH": "/evil/checkout/src"}, clear=False):
            runner.run_check("unit_tests")
        env = self._last_kwargs()["env"]
        # PYTHONPATH apunta al worktree, no al hostile.
        self.assertEqual(env["PYTHONPATH"], WORKTREE + "/src")
        self.assertNotIn("/evil", env["PYTHONPATH"])


# ---------------------------------------------------------------------------
# Sin polling/sleep en la fuente.
# ---------------------------------------------------------------------------


class NoPollingSleepTests(unittest.TestCase):
    def test_source_has_no_sleep_or_polling(self):
        self.assertNotIn("time.sleep", RUNNER_SRC)
        self.assertNotIn("while True", RUNNER_SRC)
        self.assertNotIn("datetime.now", RUNNER_SRC)


if __name__ == "__main__":
    unittest.main()
