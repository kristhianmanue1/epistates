import inspect
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from epistates.host_runner import (
    HostObserverError,
    HostRunner,
    PaneObservation,
    ProductionHostRunner,
    validate_platform_token,
    validate_session_name,
    validate_utc_timestamp,
    validate_worktree_path,
)


GIT = "/usr/bin/git"
TMUX = "/usr/bin/tmux"
CWD = "/workspace/epistates"


def _completed(stdout=b"", stderr=b"", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class _Recorder:
    """Fake ``subprocess.run`` que registra argv/kwargs y devuelve lo configurado."""

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


def _make_runner(**overrides):
    kwargs = dict(
        git_path=GIT, tmux_path=TMUX,
        timeout_seconds=5, max_output_bytes=4096,
    )
    kwargs.update(overrides)
    return ProductionHostRunner(**kwargs)


class _SubprocessTestCase(unittest.TestCase):
    def setUp(self):
        self.recorder = _Recorder()
        self.patcher = patch(
            "epistates.host_runner.subprocess.run", side_effect=self.recorder
        )
        self.mock = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _set_returns(self, *returns):
        self.recorder._returns = list(returns)
        self.recorder._index = 0

    def _set_side_effect(self, side_effect):
        self.recorder._side_effect = side_effect

    def _last_args_kwargs(self):
        return self.recorder.calls[-1]

    def _last_argv(self):
        return self._last_args_kwargs()[0][0]

    def _last_kwargs(self):
        return self._last_args_kwargs()[1]


class ProductionRunnerClosedApiTests(unittest.TestCase):
    def test_no_arbitrary_argv_api(self):
        public = {
            name for name in dir(ProductionHostRunner)
            if not name.startswith("_") and callable(getattr(ProductionHostRunner, name))
        }
        self.assertEqual(public, {
            "git_toplevel", "git_head", "git_branch", "git_status", "tmux_list_panes",
        })

    def test_closed_methods_take_no_argv_parameter(self):
        for name in ("git_toplevel", "git_head", "git_branch", "git_status"):
            params = inspect.signature(getattr(ProductionHostRunner, name)).parameters
            self.assertEqual(list(params), ["self", "cwd"])
        params = inspect.signature(ProductionHostRunner.tmux_list_panes).parameters
        self.assertEqual(list(params), ["self", "session_name"])

    def test_protocol_declares_only_closed_operations(self):
        public = {
            name for name in dir(HostRunner)
            if not name.startswith("_") and callable(getattr(HostRunner, name))
        }
        self.assertEqual(public, {
            "git_toplevel", "git_head", "git_branch", "git_status", "tmux_list_panes",
        })

    def test_constructor_rejects_relative_executable(self):
        with self.assertRaises(HostObserverError):
            _make_runner(git_path="git")
        with self.assertRaises(HostObserverError):
            _make_runner(tmux_path="tmux")

    def test_constructor_rejects_bad_timeout(self):
        for bad in (0, -1, 0.0, True, False, None, "5"):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                _make_runner(timeout_seconds=bad)

    def test_constructor_rejects_bad_max_output(self):
        for bad in (0, -1, True, False, None, "5", 17 * 1024 * 1024):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                _make_runner(max_output_bytes=bad)

    def test_constructor_rejects_non_finite_or_out_of_range_timeout(self):
        nan = float("nan")
        inf = float("inf")
        for bad in (nan, inf, -inf, 1e9, 61, 60.01, 0, -1, 0.0, True, False, None, "5"):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                _make_runner(timeout_seconds=bad)

    def test_constructor_accepts_valid_closed_timeout_range(self):
        for ok in (0.01, 1, 30, 60, 60.0):
            _make_runner(timeout_seconds=ok)  # no raise

    def test_constructor_rejects_executable_nul_root_or_unnormalized(self):
        for bad in ("/usr/bin/git\0evil", "/", "//usr/bin/git",
                    "/usr/./bin/git", "/usr/../usr/bin/git", "/usr/bin/git/"):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                _make_runner(git_path=bad)
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                _make_runner(tmux_path=bad)

    def test_constructor_does_not_require_executable_existence(self):
        # Rutas válidas pero inexistentes se aceptan: la existencia no se prueba
        # en el constructor; la inaccesibilidad se reporta al ejecutar.
        _make_runner(git_path="/nonexistent/git", tmux_path="/nonexistent/tmux")


class ProductionRunnerArgvTests(_SubprocessTestCase):
    """argv exactos, shell=False, stdin DEVNULL, cwd validado, bytes."""

    def test_git_toplevel_argv_cwd_and_subprocess_discipline(self):
        self._set_returns(_completed(stdout=b"/workspace/epistates\n"))
        runner = _make_runner()
        self.assertEqual(runner.git_toplevel(CWD), "/workspace/epistates")
        self.assertEqual(self._last_argv(), [GIT, "rev-parse", "--show-toplevel"])
        self._assert_subprocess_discipline(cwd=CWD)

    def test_git_head_argv(self):
        self._set_returns(_completed(stdout=b"7521eed0" + b"0" * 32 + b"\n"))
        runner = _make_runner()
        sha = runner.git_head(CWD)
        self.assertEqual(sha, "7521eed0" + "0" * 32)
        self.assertEqual(self._last_argv(), [GIT, "rev-parse", "HEAD"])
        self._assert_subprocess_discipline(cwd=CWD)

    def test_git_branch_argv(self):
        self._set_returns(_completed(stdout=b"codex/e1-contracts\n"))
        runner = _make_runner()
        self.assertEqual(runner.git_branch(CWD), "codex/e1-contracts")
        self.assertEqual(self._last_argv(), [GIT, "branch", "--show-current"])
        self._assert_subprocess_discipline(cwd=CWD)

    def test_git_status_argv(self):
        self._set_returns(_completed(stdout=b""))
        runner = _make_runner()
        self.assertEqual(runner.git_status(CWD), "")
        self.assertEqual(self._last_argv(), [
            GIT, "status", "--porcelain=v1", "--untracked-files=normal",
        ])
        self._assert_subprocess_discipline(cwd=CWD)

    def test_tmux_list_panes_argv_uses_printable_pipe_delimiter(self):
        self._set_returns(_completed(stdout=b"0|idle|/workspace/epistates\n"))
        runner = _make_runner()
        pane = runner.tmux_list_panes("epistates-opencode")
        self.assertEqual(pane, PaneObservation(False, "idle", "/workspace/epistates"))
        argv = self._last_argv()
        self.assertEqual(argv, [
            TMUX, "list-panes", "-t", "epistates-opencode", "-F",
            "#{pane_dead}|#{pane_current_command}|#{pane_current_path}",
        ])
        # El formato NO contiene TAB: tmux 3.6a lo sanitiza a "_" y rompería el
        # framing. El delimitador es printable.
        self.assertNotIn("\t", argv[-1])
        self.assertIn("|", argv[-1])
        kwargs = self._last_kwargs()
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIsNone(kwargs["cwd"])
        self.assertEqual(kwargs["timeout"], 5)
        self.assertIs(kwargs["check"], False)

    def test_git_methods_validate_cwd_before_subprocess(self):
        runner = _make_runner()
        for bad in ("/relative/../etc", "relative", "/", "//host", "/a/./b"):
            with self.assertRaises(HostObserverError, msg=bad):
                runner.git_toplevel(bad)
            with self.assertRaises(HostObserverError, msg=bad):
                runner.git_head(bad)
        self.assertEqual(self.mock.call_count, 0)

    def test_tmux_validates_session_before_subprocess(self):
        runner = _make_runner()
        for bad in ("a;b", "a b", "a/b", "a:b", "a.b", "", "a\nb", "-leading"):
            with self.assertRaises(HostObserverError, msg=bad):
                runner.tmux_list_panes(bad)
        self.assertEqual(self.mock.call_count, 0)

    def _assert_subprocess_discipline(self, cwd):
        kwargs = self._last_kwargs()
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(kwargs["cwd"], cwd)
        self.assertEqual(kwargs["timeout"], 5)
        self.assertIs(kwargs["check"], False)
        # Bytes: nunca text=True ni encoding.
        self.assertNotIn("text", kwargs)
        self.assertNotIn("encoding", kwargs)


class ProductionRunnerShapeTests(_SubprocessTestCase):
    def test_git_head_accepts_40_and_64_hex(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"a" * 40 + b"\n"))
        self.assertEqual(runner.git_head(CWD), "a" * 40)
        self._set_returns(_completed(stdout=b"a" * 64 + b"\n"))
        self.assertEqual(runner.git_head(CWD), "a" * 64)

    def test_git_head_rejects_non_hex(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"not-hex-but-long-enough-string\n"))
        with self.assertRaisesRegex(HostObserverError, "forma inesperada"):
            runner.git_head(CWD)

    def test_git_branch_detached_head_is_unexpected(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b""))
        with self.assertRaisesRegex(HostObserverError, "detached"):
            runner.git_branch(CWD)

    def test_git_toplevel_rejects_empty(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b""))
        with self.assertRaises(HostObserverError):
            runner.git_toplevel(CWD)

    def test_git_toplevel_rejects_embedded_newline(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"/a\n/b\n"))
        with self.assertRaisesRegex(HostObserverError, "forma inesperada"):
            runner.git_toplevel(CWD)

    def test_git_status_returns_raw_text_clean(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b""))
        self.assertEqual(runner.git_status(CWD), "")

    def test_git_status_returns_raw_text_dirty(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b" M src/file.py\n?? other\n"))
        self.assertEqual(
            runner.git_status(CWD), " M src/file.py\n?? other\n"
        )

    def test_tmux_dead_pane_parsed(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"1|idle|/workspace/epistates\n"))
        pane = runner.tmux_list_panes("epistates-opencode")
        self.assertTrue(pane.dead)

    def test_tmux_rejects_multiple_panes(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|idle|/a\n0|bash|/b\n"))
        with self.assertRaisesRegex(HostObserverError, "exactamente un pane"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_missing_field(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|idle\n"))
        with self.assertRaisesRegex(HostObserverError, "tres campos"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_extra_field(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|idle|/a|extra\n"))
        with self.assertRaisesRegex(HostObserverError, "tres campos"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_no_panes(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b""))
        with self.assertRaises(HostObserverError):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_bad_dead_flag(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"2|idle|/a\n"))
        with self.assertRaisesRegex(HostObserverError, "pane_dead"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_empty_command(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0||/a\n"))
        with self.assertRaisesRegex(HostObserverError, "campo vacío"):
            runner.tmux_list_panes("epistates-opencode")

    def test_decode_accepts_at_most_one_trailing_lf(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"/workspace/epistates\n"))
        self.assertEqual(runner.git_toplevel(CWD), "/workspace/epistates")
        self._set_returns(_completed(stdout=b"/workspace/epistates"))  # sin LF
        self.assertEqual(runner.git_toplevel(CWD), "/workspace/epistates")

    def test_decode_rejects_two_trailing_lf(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"/workspace/epistates\n\n"))
        with self.assertRaisesRegex(HostObserverError, "forma inesperada"):
            runner.git_toplevel(CWD)

    def test_decode_rejects_crlf(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"/workspace/epistates\r\n"))
        with self.assertRaisesRegex(HostObserverError, "forma inesperada"):
            runner.git_toplevel(CWD)

    def test_decode_rejects_lone_cr(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"/workspace/epistates\r"))
        with self.assertRaisesRegex(HostObserverError, "forma inesperada"):
            runner.git_toplevel(CWD)

    def test_tmux_rejects_cr_in_command(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|id\rle|/a\n"))
        with self.assertRaisesRegex(HostObserverError, "carácter de control"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_del_in_command(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|id\x7f|/a\n"))
        with self.assertRaisesRegex(HostObserverError, "carácter de control"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_del_in_path(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|idle|/a\x7f\n"))
        with self.assertRaisesRegex(HostObserverError, "carácter de control"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_rejects_other_control_in_path(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|idle|/a\x01b\n"))
        with self.assertRaisesRegex(HostObserverError, "carácter de control"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_real_36a_behavior_pipe_delimiter_roundtrips(self):
        # Emula lo que tmux 3.6a devuelve con el formato printable actual: el
        # separador ``|`` se preserva (a diferencia del TAB, que sanitiza a ``_``).
        runner = _make_runner()
        self._set_returns(
            _completed(stdout=b"0|opencode|/private/tmp/epistates-h3-slice2\n")
        )
        pane = runner.tmux_list_panes("epistates-h3-slice2")
        self.assertEqual(
            pane, PaneObservation(False, "opencode", "/private/tmp/epistates-h3-slice2")
        )

    def test_tmux_rejects_old_tab_sanitized_underscore_output(self):
        # Con el framing anterior (TAB), tmux 3.6a sustituía TAB por ``_`` y el
        # parser colapsaba. Hoy ese output (sin ``|``) se rechaza por fail-closed.
        runner = _make_runner()
        self._set_returns(
            _completed(stdout=b"0_opencode_/private/tmp/epistates-h3-slice2\n")
        )
        with self.assertRaisesRegex(HostObserverError, "tres campos"):
            runner.tmux_list_panes("epistates-h3-slice2")

    def test_tmux_pipe_collision_in_path_fails_closed(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|idle|/a|b\n"))
        with self.assertRaisesRegex(HostObserverError, "tres campos"):
            runner.tmux_list_panes("epistates-opencode")

    def test_tmux_pipe_collision_in_command_fails_closed(self):
        runner = _make_runner()
        self._set_returns(_completed(stdout=b"0|a|b|/path\n"))
        with self.assertRaisesRegex(HostObserverError, "tres campos"):
            runner.tmux_list_panes("epistates-opencode")


class ProductionRunnerFailClosedTests(_SubprocessTestCase):
    def _assert_no_leak(self, exc, secret):
        message = str(exc.exception)
        self.assertNotIn(secret, message)
        self.assertNotIn("stdout", message.lower())
        self.assertNotIn("stderr", message.lower())

    def test_timeout_is_fail_closed_without_leak(self):
        self._set_side_effect(
            subprocess.TimeoutExpired(cmd=["git"], timeout=5)
        )
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "timeout"):
            runner.git_toplevel(CWD)

    def test_missing_executable_is_fail_closed(self):
        self._set_side_effect(FileNotFoundError(2, "No such file"))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "executable ausente"):
            runner.git_toplevel(CWD)

    def test_nonzero_exit_is_fail_closed_without_leak(self):
        secret = "TOPSECRET-stderr-content"
        self._set_returns(_completed(stderr=secret.encode(), returncode=1))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "exit no cero") as exc:
            runner.git_toplevel(CWD)
        self._assert_no_leak(exc, secret)

    def test_overflow_is_fail_closed_without_leak(self):
        secret = b"X" * 5000
        self._set_returns(_completed(stdout=secret, stderr=secret))
        runner = _make_runner(max_output_bytes=4096)
        with self.assertRaisesRegex(HostObserverError, "límite") as exc:
            runner.git_toplevel(CWD)
        self.assertNotIn("X" * 100, str(exc.exception))

    def test_invalid_utf8_is_fail_closed(self):
        self._set_returns(_completed(stdout=b"\xff\xfe\xfd\n"))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "UTF-8"):
            runner.git_toplevel(CWD)

    def test_nul_byte_is_fail_closed(self):
        self._set_returns(_completed(stdout=b"ok\x00evil\n"))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "NUL"):
            runner.git_toplevel(CWD)

    def test_nul_byte_in_status_is_fail_closed(self):
        self._set_returns(_completed(stdout=b" M a\x00b\n"))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "NUL"):
            runner.git_status(CWD)

    def test_invalid_utf8_in_tmux_is_fail_closed(self):
        self._set_returns(_completed(stdout=b"\xff|idle|/a\n"))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "UTF-8"):
            runner.tmux_list_panes("epistates-opencode")

    def test_stderr_nonempty_with_exit_zero_is_fail_closed(self):
        secret = "ANOMALOUS-stderr-warning"
        self._set_returns(_completed(stdout=b"/path\n", stderr=secret.encode(), returncode=0))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "stderr no vacío") as exc:
            runner.git_toplevel(CWD)
        self.assertNotIn(secret, str(exc.exception))

    def test_overflow_is_checked_before_exit(self):
        # returncode 1 Y overflow: prevalece el overflow (antes de exit).
        self._set_returns(_completed(stdout=b"X" * 5000, stderr=b"Y" * 5000, returncode=1))
        runner = _make_runner(max_output_bytes=4096)
        with self.assertRaisesRegex(HostObserverError, "límite"):
            runner.git_toplevel(CWD)

    def test_permission_error_is_fail_closed_without_leak(self):
        self._set_side_effect(PermissionError(13, "Permission denied: /secret/path"))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "executable ausente o inaccesible") as exc:
            runner.git_toplevel(CWD)
        self.assertNotIn("secret", str(exc.exception))

    def test_generic_oserror_is_fail_closed_without_leak(self):
        self._set_side_effect(OSError("boom-secret-detail"))
        runner = _make_runner()
        with self.assertRaisesRegex(HostObserverError, "executable ausente o inaccesible") as exc:
            runner.git_toplevel(CWD)
        self.assertNotIn("boom-secret", str(exc.exception))


class ProductionRunnerEnvTests(_SubprocessTestCase):
    def _env_of_last_call(self):
        return self._last_kwargs()["env"]

    def test_env_is_minimal_and_built_from_scratch(self):
        self._set_returns(_completed(stdout=b"/path\n"))
        runner = _make_runner()
        runner.git_toplevel(CWD)
        env = self._env_of_last_call()
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["LANG"], "C")
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")

    def test_env_excludes_inherited_and_hostile_keys(self):
        self._set_returns(_completed(stdout=b"/path\n"))
        runner = _make_runner()
        runner.git_toplevel(CWD)
        env = self._env_of_last_call()
        for forbidden in ("HOME", "PATH", "GIT_DIR", "GIT_WORK_TREE",
                          "GIT_CONFIG_COUNT", "GIT_INDEX_FILE", "GIT_AUTHOR_NAME",
                          "TMUX", "TMUX_TMPDIR", "TERM", "USER"):
            self.assertNotIn(forbidden, env, forbidden)

    def test_env_does_not_inherit_hostile_process_env(self):
        import os
        hostile = {
            "GIT_DIR": "/evil/git", "GIT_WORK_TREE": "/evil/wt",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.email",
            "GIT_CONFIG_VALUE_0": "evil@example.com",
            "TMUX_TMPDIR": "/evil/tmp", "HOME": "/evil/home",
            "PATH": "/evil/bin",
        }
        self._set_returns(_completed(stdout=b"/path\n"))
        runner = _make_runner()
        with patch.dict(os.environ, hostile, clear=False):
            runner.git_toplevel(CWD)
        env = self._env_of_last_call()
        # La no herencia se prueba por clave: el runner construye desde cero y
        # ninguna variable hostil del proceso aparece en el env del hijo.
        for key in hostile:
            self.assertNotIn(key, env, key)
        # Y los valores distintivamente hostiles tampoco se cuelan.
        distinctive = ("/evil/git", "/evil/wt", "evil@example.com", "/evil/tmp", "/evil/bin")
        rendered_values = ",".join(env.values())
        for needle in distinctive:
            self.assertNotIn(needle, rendered_values, needle)

    def test_tmux_call_also_uses_minimal_env(self):
        self._set_returns(_completed(stdout=b"0|idle|/a\n"))
        runner = _make_runner()
        runner.tmux_list_panes("epistates-opencode")
        env = self._env_of_last_call()
        self.assertNotIn("TMUX", env)
        self.assertNotIn("TMUX_TMPDIR", env)
        self.assertNotIn("HOME", env)
        self.assertNotIn("PATH", env)


class ValidatorTests(unittest.TestCase):
    def test_validate_worktree_path_accepts_normalized_absolute(self):
        self.assertEqual(validate_worktree_path("/workspace/epistates"), "/workspace/epistates")

    def test_validate_worktree_path_rejects_hostile(self):
        for bad in (None, 5, "", "relative", "/", "//host", "/a/../b", "/a/./b", "/a//b"):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                validate_worktree_path(bad)

    def test_validate_session_name_accepts_closed(self):
        self.assertEqual(validate_session_name("epistates-opencode"), "epistates-opencode")
        self.assertEqual(validate_session_name("a"), "a")
        self.assertEqual(validate_session_name("A_B-c3"), "A_B-c3")

    def test_validate_session_name_rejects_hostile(self):
        for bad in (None, 5, "", "a;b", "a b", "a/b", "a:b", "a.b", "a\nb", "-lead", "a" * 65):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                validate_session_name(bad)

    def test_validate_platform_token_accepts_canonical(self):
        self.assertEqual(validate_platform_token("darwin"), "darwin")
        self.assertEqual(validate_platform_token("linux"), "linux")

    def test_validate_platform_token_rejects_non_canonical(self):
        for bad in (None, 5, "", "Darwin", "win 32", "x/y", "a\nb"):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                validate_platform_token(bad)

    def test_validate_utc_timestamp_accepts_canonical(self):
        self.assertEqual(
            validate_utc_timestamp("2026-08-11T18:00:00Z"),
            "2026-08-11T18:00:00Z",
        )
        self.assertEqual(
            validate_utc_timestamp("2026-08-11T18:00:00.123Z"),
            "2026-08-11T18:00:00.123Z",
        )
        # 2024 es bisiesto: 29 de febrero válido.
        self.assertEqual(
            validate_utc_timestamp("2024-02-29T00:00:00Z"),
            "2024-02-29T00:00:00Z",
        )

    def test_validate_utc_timestamp_rejects_non_canonical(self):
        for bad in (None, 5, "", "2026-08-11 18:00:00Z", "2026-08-11T18:00:00+02:00", "x"):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                validate_utc_timestamp(bad)

    def test_validate_utc_timestamp_rejects_invalid_calendar_dates(self):
        # El regex acepta estos dígitos, pero datetime debe rechazarlos.
        for bad in ("2026-99-99T00:00:00Z", "2026-13-01T00:00:00Z",
                    "2026-02-30T00:00:00Z", "2026-00-10T00:00:00Z",
                    "2026-08-00T00:00:00Z", "2026-08-11T25:00:00Z",
                    "2026-08-11T00:60:00Z", "2026-08-11T00:00:60Z",
                    "2024-02-30T00:00:00Z"):
            with self.assertRaises(HostObserverError, msg=repr(bad)):
                validate_utc_timestamp(bad)


if __name__ == "__main__":
    unittest.main()
