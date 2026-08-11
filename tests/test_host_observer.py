import copy
import inspect
import json
import os
import subprocess
import unittest
from pathlib import Path

from epistates.host_observer import observe_opencode_tmux
from epistates.host_runner import (
    HostObserverError,
    HostRunner,
    PaneObservation,
    ProductionHostRunner,
)
from epistates.preflight import evaluate_preflight


FIXTURES = Path(__file__).parent.parent / "fixtures"

WORKTREE = "/workspace/epistates"
SHA = "7521eed0000000000000000000000000000000000"
BRANCH = "codex/e1-contracts"
SESSION = "epistates-opencode"
COMMAND = "idle"
PLATFORM = "darwin"
OBSERVED_AT = "2026-08-11T18:00:00Z"

EXPECTED_KEYS = (
    "observed_repository",
    "observed_worktree",
    "observed_cwd",
    "observed_branch",
    "observed_sha",
    "worktree_clean",
    "observed_session_name",
    "pane_alive",
    "observed_command",
    "observed_platform",
    "observed_at",
)


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeRunner:
    """Runner determinista que registra la secuencia de llamadas."""

    def __init__(self, toplevel, head, branch, status, pane):
        self.toplevel = toplevel
        self.head = head
        self.branch = branch
        self.status = status
        self.pane = pane
        self.calls = []

    def git_toplevel(self, cwd):
        self.calls.append(("git_toplevel", cwd))
        return self.toplevel

    def git_head(self, cwd):
        self.calls.append(("git_head", cwd))
        return self.head

    def git_branch(self, cwd):
        self.calls.append(("git_branch", cwd))
        return self.branch

    def git_status(self, cwd):
        self.calls.append(("git_status", cwd))
        return self.status

    def tmux_list_panes(self, session_name):
        self.calls.append(("tmux_list_panes", session_name))
        return self.pane


def _nominal_runner():
    return FakeRunner(
        toplevel=WORKTREE, head=SHA, branch=BRANCH, status="",
        pane=PaneObservation(False, COMMAND, WORKTREE),
    )


def _default_task():
    return load("task-card-valid.json")


def _default_adapter():
    return load("adapter-capabilities-opencode-tmux.json")


class ObserveOpencodeTmuxTests(unittest.TestCase):
    def setUp(self):
        self.task = _default_task()
        self.adapter = _default_adapter()
        self.runner = _nominal_runner()

    def call(self, **overrides):
        task = overrides.pop("task", None) or self.task
        runner = overrides.pop("runner", None) or self.runner
        kwargs = dict(
            session_name=SESSION, observed_at=OBSERVED_AT,
            platform_name=PLATFORM, runner=runner,
        )
        kwargs.update(overrides)
        return observe_opencode_tmux(task, **kwargs)

    def test_fake_runner_satisfies_protocol(self):
        # El fake implementa el contrato del runner inyectable.
        self.assertTrue(hasattr(self.runner, "git_toplevel"))
        self.assertTrue(hasattr(self.runner, "tmux_list_panes"))

    def test_no_arbitrary_command_parameter(self):
        params = inspect.signature(observe_opencode_tmux).parameters
        self.assertEqual(
            list(params),
            ["task_card", "session_name", "observed_at", "platform_name", "runner"],
        )
        for forbidden in ("argv", "command", "cmd", "shell", "script"):
            self.assertNotIn(forbidden, params)

    def test_observer_does_not_couple_to_preflight(self):
        import epistates.host_observer as module
        self.assertFalse(hasattr(module, "evaluate_preflight"))
        self.assertFalse(hasattr(module, "validate_preflight_result"))

    def test_nominal_produces_exactly_eleven_keys(self):
        result = self.call()
        self.assertEqual(set(result), set(EXPECTED_KEYS))
        self.assertEqual(len(result), 11)
        self.assertEqual(tuple(result), EXPECTED_KEYS)

    def test_nominal_values_come_from_runner_and_args(self):
        result = self.call()
        self.assertEqual(result["observed_repository"], "epistates")
        self.assertEqual(result["observed_worktree"], WORKTREE)
        self.assertEqual(result["observed_cwd"], WORKTREE)
        self.assertEqual(result["observed_branch"], BRANCH)
        self.assertEqual(result["observed_sha"], SHA)
        self.assertIs(result["worktree_clean"], True)
        self.assertEqual(result["observed_session_name"], SESSION)
        self.assertIs(result["pane_alive"], True)
        self.assertEqual(result["observed_command"], COMMAND)
        self.assertEqual(result["observed_platform"], PLATFORM)
        self.assertEqual(result["observed_at"], OBSERVED_AT)

    def test_repository_is_basename_of_toplevel_not_target_repository(self):
        # El nombre proviene del toplevel observado, no de target.repository.
        runner = FakeRunner(
            toplevel="/srv/customname", head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(False, COMMAND, "/srv/customname"),
        )
        result = self.call(runner=runner)
        self.assertEqual(result["observed_repository"], "customname")
        self.assertEqual(result["observed_worktree"], "/srv/customname")

    def test_repository_with_distinct_name_is_preserved_for_preflight_block(self):
        # El observer NO sobrescribe el nombre para hacerlo coincidir.
        runner = FakeRunner(
            toplevel="/workspace/other", head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(False, COMMAND, "/workspace/other"),
        )
        result = self.call(runner=runner)
        self.assertEqual(result["observed_repository"], "other")

    def test_observed_worktree_passes_raw_without_normalization(self):
        runner = FakeRunner(
            toplevel="/workspace/./epistates", head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(False, COMMAND, "/workspace/./epistates"),
        )
        result = self.call(runner=runner)
        # Sin normalización silenciosa: pasa crudo.
        self.assertEqual(result["observed_worktree"], "/workspace/./epistates")
        self.assertEqual(result["observed_cwd"], "/workspace/./epistates")

    def test_observed_cwd_comes_from_pane(self):
        runner = FakeRunner(
            toplevel=WORKTREE, head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(False, COMMAND, "/workspace/epistates/sub"),
        )
        result = self.call(runner=runner)
        self.assertEqual(result["observed_cwd"], "/workspace/epistates/sub")

    def test_dirty_status_sets_worktree_clean_false(self):
        runner = FakeRunner(
            toplevel=WORKTREE, head=SHA, branch=BRANCH, status=" M src/file.py\n",
            pane=PaneObservation(False, COMMAND, WORKTREE),
        )
        result = self.call(runner=runner)
        self.assertIs(result["worktree_clean"], False)

    def test_dead_pane_sets_pane_alive_false(self):
        runner = FakeRunner(
            toplevel=WORKTREE, head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(True, COMMAND, WORKTREE),
        )
        result = self.call(runner=runner)
        self.assertIs(result["pane_alive"], False)

    def test_order_of_operations_is_deterministic(self):
        runner = _nominal_runner()
        self.call(runner=runner)
        self.assertEqual(
            [name for name, _ in runner.calls],
            ["git_toplevel", "git_head", "git_branch", "git_status", "tmux_list_panes"],
        )

    def test_git_calls_use_worktree_as_cwd_and_tmux_uses_session(self):
        runner = _nominal_runner()
        self.call(runner=runner)
        self.assertEqual(runner.calls[0], ("git_toplevel", WORKTREE))
        self.assertEqual(runner.calls[1], ("git_head", WORKTREE))
        self.assertEqual(runner.calls[2], ("git_branch", WORKTREE))
        self.assertEqual(runner.calls[3], ("git_status", WORKTREE))
        self.assertEqual(runner.calls[4], ("tmux_list_panes", SESSION))

    def test_does_not_mutate_task_card(self):
        snapshot = copy.deepcopy(self.task)
        self.call()
        self.assertEqual(self.task, snapshot)

    def test_empty_status_is_clean_strict(self):
        runner = FakeRunner(
            toplevel=WORKTREE, head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(False, COMMAND, WORKTREE),
        )
        self.assertIs(self.call(runner=runner)["worktree_clean"], True)

    def test_whitespace_only_status_is_dirty_not_clean(self):
        # Cualquier byte (incluido whitespace anomalo) implica dirty: no strip().
        for anomalous in ("   ", "\n", " \n ", "\t", "\r\n"):
            runner = FakeRunner(
                toplevel=WORKTREE, head=SHA, branch=BRANCH, status=anomalous,
                pane=PaneObservation(False, COMMAND, WORKTREE),
            )
            result = self.call(runner=runner)
            self.assertIs(result["worktree_clean"], False, msg=repr(anomalous))

    def test_invalid_calendar_date_fails_before_runner_call(self):
        runner = _nominal_runner()
        with self.assertRaises(HostObserverError):
            observe_opencode_tmux(
                self.task, SESSION, "2026-99-99T00:00:00Z", PLATFORM, runner,
            )
        self.assertEqual(runner.calls, [])

    def test_globally_invalid_card_with_valid_worktree_fails_before_runner(self):
        task = copy.deepcopy(self.task)
        del task["objective"]  # worktree sigue válido; tarjeta globalmente inválida
        runner = _nominal_runner()
        with self.assertRaises(HostObserverError) as exc:
            observe_opencode_tmux(task, SESSION, OBSERVED_AT, PLATFORM, runner)
        # Mensaje saneado: no filtra el detalle de validación de la tarjeta.
        self.assertNotIn("objective", str(exc.exception))
        self.assertEqual(runner.calls, [])

    def test_hostile_worktree_fails_before_any_runner_call(self):
        task = copy.deepcopy(self.task)
        task["target"]["worktree"] = "/workspace/../etc"
        runner = _nominal_runner()
        with self.assertRaises(HostObserverError):
            observe_opencode_tmux(task, SESSION, OBSERVED_AT, PLATFORM, runner)
        self.assertEqual(runner.calls, [])

    def test_hostile_session_fails_closed(self):
        runner = _nominal_runner()
        with self.assertRaises(HostObserverError):
            observe_opencode_tmux(
                self.task, "host;evil", OBSERVED_AT, PLATFORM, runner,
            )
        self.assertEqual(runner.calls, [])

    def test_hostile_observed_at_fails_closed(self):
        with self.assertRaises(HostObserverError):
            self.call(observed_at="2026-08-11 18:00:00Z")

    def test_hostile_platform_fails_closed(self):
        with self.assertRaises(HostObserverError):
            self.call(platform_name="Darwin")
        with self.assertRaises(HostObserverError):
            self.call(platform_name="x/y")

    def test_none_runner_fails_closed(self):
        with self.assertRaises(HostObserverError):
            observe_opencode_tmux(self.task, SESSION, OBSERVED_AT, PLATFORM, None)

    def test_non_mapping_task_fails_closed(self):
        with self.assertRaises(HostObserverError):
            observe_opencode_tmux(["not", "mapping"], SESSION, OBSERVED_AT, PLATFORM, self.runner)

    def test_missing_target_fails_closed(self):
        task = copy.deepcopy(self.task)
        del task["target"]
        with self.assertRaises(HostObserverError):
            observe_opencode_tmux(task, SESSION, OBSERVED_AT, PLATFORM, self.runner)

    def test_determinism(self):
        first = self.call()
        second = self.call()
        self.assertEqual(first, second)


class ObserveToIntegrationTests(unittest.TestCase):
    """Integración pura observe_opencode_tmux -> evaluate_preflight."""

    def _evaluate(self, observations):
        return evaluate_preflight(
            _default_task(), _default_adapter(), observations,
            expected_run_id="run-001", expected_attempt_id="attempt-001",
            expected_session_name=SESSION, expected_command=COMMAND,
        )

    def test_nominal_pipeline_produces_ok(self):
        runner = _nominal_runner()
        observations = observe_opencode_tmux(
            _default_task(), SESSION, OBSERVED_AT, PLATFORM, runner,
        )
        result = self._evaluate(observations)
        self.assertEqual(result["outcome"], "ok")
        self.assertEqual(result["reasons"], [])

    def test_distinct_repository_pipeline_blocks_with_repository_mismatch(self):
        runner = FakeRunner(
            toplevel="/workspace/other", head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(False, COMMAND, "/workspace/other"),
        )
        observations = observe_opencode_tmux(
            _default_task(), SESSION, OBSERVED_AT, PLATFORM, runner,
        )
        result = self._evaluate(observations)
        # El basename difiere -> repository_mismatch; como el path también difiere
        # de target.worktree, worktree y cwd mismatches se suman en orden canónico.
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(
            result["reasons"],
            ["repository_mismatch", "worktree_mismatch", "cwd_mismatch"],
        )

    def test_dirty_pipeline_blocks_with_dirty(self):
        runner = FakeRunner(
            toplevel=WORKTREE, head=SHA, branch=BRANCH, status=" M file.py\n",
            pane=PaneObservation(False, COMMAND, WORKTREE),
        )
        observations = observe_opencode_tmux(
            _default_task(), SESSION, OBSERVED_AT, PLATFORM, runner,
        )
        result = self._evaluate(observations)
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("dirty", result["reasons"])

    def test_dead_pane_pipeline_blocks_with_pane_dead(self):
        runner = FakeRunner(
            toplevel=WORKTREE, head=SHA, branch=BRANCH, status="",
            pane=PaneObservation(True, COMMAND, WORKTREE),
        )
        observations = observe_opencode_tmux(
            _default_task(), SESSION, OBSERVED_AT, PLATFORM, runner,
        )
        result = self._evaluate(observations)
        self.assertIn("pane_dead", result["reasons"])


class RealTmuxSmokeTest(unittest.TestCase):
    """Smoke read-only real: git + tmux reales contra el worktree y la sesión.

    Se salta (skip) si los executables reales o la sesión no están presentes,
    de modo que la suite siga siendo portable. Cuando el entorno existe,
    observa el host real y comprueba que el preflight bloquea únicamente por
    ``dirty`` (hay cambios sin commit en este worktree).
    """

    GIT = "/usr/bin/git"
    TMUX = "/opt/homebrew/bin/tmux"
    WORKTREE = "/private/tmp/epistates-h3-slice2"
    SESSION = "epistates-h3-slice2"
    _ENV = {
        "LC_ALL": "C", "LANG": "C", "PATH": "/usr/bin:/bin",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }

    def setUp(self):
        if not (Path(self.GIT).exists() and Path(self.TMUX).exists()):
            self.skipTest("se requiere /usr/bin/git y /opt/homebrew/bin/tmux")

    def _git(self, *args):
        proc = subprocess.run(
            [self.GIT, "-C", self.WORKTREE, *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, shell=False, env=self._ENV,
        )
        return proc.stdout.decode("utf-8").strip()

    def _adapter(self):
        return {
            "schema": "epistates/adapter-capabilities/v1",
            "adapter_id": "opencode-tmux", "version": "v1",
            "platforms": ["darwin", "linux"],
            "capabilities": ["dispatch_literal", "observe_session", "capture_once"],
        }

    def _task_card(self, repository, head, branch):
        return {
            "schema": "epistates/task-card/v1",
            "task_id": "h3-slice2-smoke",
            "objective": "Smoke read-only real del host.",
            "target": {
                "repository": repository, "base_sha": head,
                "branch": branch, "worktree": self.WORKTREE,
            },
            "role": "developer",
            "authority": {
                "grant_id": "smoke-grant", "granted_by": "maintainer",
                "granted_actions": ["read", "edit", "run_checks"],
                "protected_operations_authorized": [],
            },
            "allowed_paths": ["src/", "tests/", "docs/"],
            "allowed_actions": ["read", "edit", "run_checks"],
            "forbidden_operations": [
                "commit", "push", "open_pr", "merge", "release",
                "install_dependencies", "change_scope",
            ],
            "inputs": ["docs/plan-inicial.md"],
            "checks": [{"check_id": "unit_tests", "expected": "exit 0"}],
            "evidence": {
                "report_format": "rag/v1",
                "required": ["worktree_status", "diff_check", "check_results"],
            },
            "delivery": "RAG",
            "stop_condition": "detener tras el smoke",
            "new_decision_required_for": ["commit"],
        }

    def test_real_observation_blocks_only_by_dirty(self):
        try:
            head = self._git("rev-parse", "HEAD")
            branch = self._git("branch", "--show-current")
            toplevel = self._git("rev-parse", "--show-toplevel")
        except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
            self.skipTest("git read falló en el worktree real")
        repository = os.path.basename(toplevel.rstrip("/"))
        task_card = self._task_card(repository, head, branch)
        runner = ProductionHostRunner(self.GIT, self.TMUX, 10, 65536)
        try:
            obs = observe_opencode_tmux(
                task_card, self.SESSION, "2026-08-11T18:00:00Z", "darwin", runner,
            )
        except HostObserverError:
            self.skipTest("la sesión tmux real no es observable")
        # El formato printable ``|`` debe preservarse: la observación trae
        # command y path no vacíos.
        self.assertTrue(obs["observed_command"])
        self.assertTrue(obs["observed_cwd"])
        result = evaluate_preflight(
            task_card, self._adapter(), obs,
            expected_run_id="smoke-run", expected_attempt_id="smoke-attempt",
            expected_session_name=self.SESSION,
            expected_command=obs["observed_command"],
        )
        # Worktree con cambios sin commit -> bloqueado únicamente por dirty.
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reasons"], ["dirty"], result)


if __name__ == "__main__":
    unittest.main()
