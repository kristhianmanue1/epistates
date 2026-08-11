import copy
import json
import unittest
from pathlib import Path

from epistates.audit import canonical_digest
from epistates.contracts import ValidationError
from epistates.preflight import (
    PreflightError,
    evaluate_preflight,
    validate_preflight_binding,
    validate_preflight_result,
)


FIXTURES = Path(__file__).parent.parent / "fixtures"

RUN_ID = "run-001"
ATTEMPT_ID = "attempt-001"
SESSION_NAME = "epistates-opencode"
COMMAND = "idle"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class EvaluatePreflightTests(unittest.TestCase):
    def setUp(self):
        self.task = load("task-card-valid.json")
        self.adapter = load("adapter-capabilities-opencode-tmux.json")
        self.observations = load("run-context-ok.json")

    def call(self, **overrides):
        task = overrides.pop("task", None) or self.task
        adapter = overrides.pop("adapter", None) or self.adapter
        observations = overrides.pop("observations", None) or self.observations
        kwargs = dict(
            expected_run_id=RUN_ID, expected_attempt_id=ATTEMPT_ID,
            expected_session_name=SESSION_NAME, expected_command=COMMAND,
        )
        kwargs.update(overrides)
        return evaluate_preflight(task, adapter, observations, **kwargs)

    def test_nominal_returns_ok_with_empty_reasons(self):
        result = self.call()
        self.assertEqual(result["outcome"], "ok")
        self.assertEqual(result["reasons"], [])

    def test_nominal_matches_ok_fixture_exactly(self):
        result = self.call()
        self.assertEqual(result, load("preflight-result-ok.json"))

    def test_digests_are_canonical(self):
        result = self.call()
        self.assertEqual(result["task_card_digest"], canonical_digest(self.task))
        self.assertEqual(result["adapter_digest"], canonical_digest(self.adapter))

    def test_observed_block_excludes_observed_at(self):
        result = self.call()
        self.assertNotIn("observed_at", result["observed"])
        self.assertEqual(result["observed_at"], self.observations["observed_at"])

    def _blocked_with(self, reason, **mutations):
        observations = copy.deepcopy(self.observations)
        for key, value in mutations.items():
            observations[key] = value
        result = self.call(observations=observations)
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn(reason, result["reasons"])
        return result

    def test_repository_mismatch(self):
        self._blocked_with("repository_mismatch", observed_repository="other")

    def test_worktree_mismatch(self):
        self._blocked_with("worktree_mismatch", observed_worktree="/other/path")

    def test_cwd_mismatch_is_exact_not_containment(self):
        # cwd dentro del worktree pero distinto: debe bloquear (no containment).
        self._blocked_with("cwd_mismatch", observed_cwd="/workspace/epistates/sub")

    def test_branch_drift(self):
        self._blocked_with("branch_drift", observed_branch="codex/other")

    def test_sha_drift(self):
        self._blocked_with("sha_drift", observed_sha="0" * 40)

    def test_dirty(self):
        self._blocked_with("dirty", worktree_clean=False)

    def test_session_mismatch(self):
        self._blocked_with("session_mismatch", observed_session_name="other")

    def test_pane_dead(self):
        self._blocked_with("pane_dead", pane_alive=False)

    def test_command_unexpected(self):
        self._blocked_with("command_unexpected", observed_command="rm -rf /")

    def test_platform_unsupported_when_adapter_lacks_it(self):
        adapter = copy.deepcopy(self.adapter)
        adapter["platforms"] = ["linux"]
        result = self.call(adapter=adapter)
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("platform_unsupported", result["reasons"])

    def test_unsupported_platform_token_is_blocked_not_raised(self):
        # Un token bien tipado pero ausente del manifiesto produce un resultado
        # portable blocked, no PreflightError.
        observations = copy.deepcopy(self.observations)
        observations["observed_platform"] = "windows"
        result = self.call(observations=observations)
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reasons"], ["platform_unsupported"])

    def test_multiple_reasons_keep_deterministic_order(self):
        observations = copy.deepcopy(self.observations)
        observations["observed_branch"] = "codex/other"
        observations["worktree_clean"] = False
        result = self.call(observations=observations)
        self.assertEqual(result["reasons"], ["branch_drift", "dirty"])

    def test_missing_observation_raises(self):
        observations = copy.deepcopy(self.observations)
        del observations["observed_sha"]
        with self.assertRaisesRegex(PreflightError, "ausentes"):
            self.call(observations=observations)

    def test_unknown_observation_key_raises(self):
        observations = copy.deepcopy(self.observations)
        observations["extra"] = "x"
        with self.assertRaisesRegex(PreflightError, "no soportadas"):
            self.call(observations=observations)

    def test_ill_typed_observation_raises_without_traceback(self):
        cases = [
            ("worktree_clean", 1),
            ("pane_alive", "yes"),
            ("observed_sha", "not-hex"),
            ("observed_platform", ["darwin"]),
            ("observed_platform", "Darwin"),
            ("observed_platform", "win 32"),
            ("observed_platform", "x/y"),
            ("observed_platform", "win\ndows"),
            ("observed_repository", "  "),
            ("observed_session_name", "\ud800"),
            ("observed_command", ""),
            ("observed_command", "   "),
        ]
        for key, value in cases:
            observations = copy.deepcopy(self.observations)
            observations[key] = value
            with self.assertRaises(PreflightError, msg=key):
                self.call(observations=observations)

    def test_bad_observed_at_raises(self):
        for bad in ("2026-08-11 18:00:00Z", "2026-08-11T18:00:00+02:00", "not-a-date"):
            observations = copy.deepcopy(self.observations)
            observations["observed_at"] = bad
            with self.assertRaises(PreflightError):
                self.call(observations=observations)

    def test_non_mapping_observations_raises(self):
        with self.assertRaises(PreflightError):
            self.call(observations=["not", "mapping"])

    def test_bad_card_raises_validation_error(self):
        task = copy.deepcopy(self.task)
        del task["target"]
        with self.assertRaises(ValidationError):
            self.call(task=task)

    def test_bad_adapter_raises_validation_error(self):
        adapter = copy.deepcopy(self.adapter)
        adapter["platforms"] = ["windows"]
        with self.assertRaises(ValidationError):
            self.call(adapter=adapter)

    def test_bad_controller_args_raise_validation_error(self):
        with self.assertRaisesRegex(ValidationError, "expected_run_id"):
            self.call(expected_run_id="UPPER")
        with self.assertRaisesRegex(ValidationError, "expected_session_name"):
            self.call(expected_session_name="   ")
        with self.assertRaisesRegex(ValidationError, "expected_command"):
            self.call(expected_command="\ud800")
        with self.assertRaisesRegex(ValidationError, "expected_command"):
            self.call(expected_command="")
        with self.assertRaisesRegex(ValidationError, "expected_command"):
            self.call(expected_command="   ")

    def test_evaluating_blocked_matches_blocked_fixture(self):
        result = self.call(observations=load("run-context-ok.json"))
        # El fixture bloqueado muta branch y dirty; reproducimos sus observaciones.
        observations = copy.deepcopy(self.observations)
        observations["observed_branch"] = "codex/other"
        observations["worktree_clean"] = False
        result = self.call(observations=observations)
        self.assertEqual(result, load("preflight-result-blocked.json"))

    def test_does_not_mutate_inputs(self):
        task_snap = copy.deepcopy(self.task)
        adapter_snap = copy.deepcopy(self.adapter)
        obs_snap = copy.deepcopy(self.observations)
        self.call()
        self.assertEqual(self.task, task_snap)
        self.assertEqual(self.adapter, adapter_snap)
        self.assertEqual(self.observations, obs_snap)

    def test_determinism(self):
        first = self.call()
        second = self.call()
        self.assertEqual(first, second)


class PreflightResultValidationTests(unittest.TestCase):
    def test_accepts_ok_fixture(self):
        validate_preflight_result(load("preflight-result-ok.json"))

    def test_accepts_blocked_fixture(self):
        validate_preflight_result(load("preflight-result-blocked.json"))

    def test_ok_with_reasons_rejected(self):
        result = load("preflight-result-ok.json")
        result["reasons"] = ["dirty"]
        with self.assertRaisesRegex(ValidationError, "ok exige"):
            validate_preflight_result(result)

    def test_blocked_without_reasons_rejected(self):
        result = load("preflight-result-blocked.json")
        result["reasons"] = []
        with self.assertRaisesRegex(ValidationError, "blocked exige"):
            validate_preflight_result(result)

    def test_duplicate_reason_rejected(self):
        result = load("preflight-result-blocked.json")
        result["reasons"] = ["dirty", "dirty"]
        with self.assertRaisesRegex(ValidationError, "duplicado"):
            validate_preflight_result(result)

    def test_unknown_reason_rejected(self):
        result = load("preflight-result-blocked.json")
        result["reasons"] = ["unknown_reason"]
        with self.assertRaisesRegex(ValidationError, "catalogo"):
            validate_preflight_result(result)

    def test_out_of_order_reasons_rejected(self):
        result = load("preflight-result-blocked.json")
        result["reasons"] = ["dirty", "branch_drift"]
        with self.assertRaisesRegex(ValidationError, "orden canonico"):
            validate_preflight_result(result)

    def test_bad_observed_field_rejected(self):
        result = load("preflight-result-ok.json")
        result["observed"]["worktree_clean"] = "yes"
        with self.assertRaises(ValidationError):
            validate_preflight_result(result)

    def test_non_canonical_platform_token_rejected(self):
        for bad in ("Darwin", "win 32", "x/y", "win\ndows"):
            result = copy.deepcopy(load("preflight-result-ok.json"))
            result["observed"]["observed_platform"] = bad
            with self.assertRaises(ValidationError, msg=bad):
                validate_preflight_result(result)

    def test_structural_validation_does_not_equal_binding(self):
        # digest con formato valido pero incorrecto: la estructura pasa, el binding no.
        result = load("preflight-result-ok.json")
        tampered = copy.deepcopy(result)
        tampered["task_card_digest"] = "sha256:" + "0" * 64
        validate_preflight_result(tampered)  # no levanta
        with self.assertRaisesRegex(ValidationError, "task_card_digest"):
            validate_preflight_binding(
                tampered, load("task-card-valid.json"),
                load("adapter-capabilities-opencode-tmux.json"),
                RUN_ID, ATTEMPT_ID, SESSION_NAME, COMMAND,
            )


class PreflightBindingTests(unittest.TestCase):
    def bind(self, result=None, **overrides):
        task = overrides.pop("task", None) or load("task-card-valid.json")
        adapter = overrides.pop("adapter", None) or load("adapter-capabilities-opencode-tmux.json")
        kwargs = dict(
            expected_run_id=RUN_ID, expected_attempt_id=ATTEMPT_ID,
            expected_session_name=SESSION_NAME, expected_command=COMMAND,
        )
        kwargs.update(overrides)
        validate_preflight_binding(result or load("preflight-result-ok.json"), task, adapter, **kwargs)

    def test_ok_fixture_binds(self):
        self.bind()

    def test_blocked_fixture_binds_when_context_matches(self):
        self.bind(result=load("preflight-result-blocked.json"))

    def test_wrong_run_id_rejected(self):
        with self.assertRaisesRegex(ValidationError, "run_id"):
            self.bind(expected_run_id="run-999")

    def test_wrong_attempt_id_rejected(self):
        with self.assertRaisesRegex(ValidationError, "attempt_id"):
            self.bind(expected_attempt_id="attempt-999")

    def test_wrong_adapter_id_rejected(self):
        result = copy.deepcopy(load("preflight-result-ok.json"))
        result["adapter_id"] = "another-tool"
        with self.assertRaisesRegex(ValidationError, "adapter_id"):
            self.bind(result=result)

    def test_wrong_session_rejected_as_incoherent(self):
        # OK nominal ligado contra otra sesion: el recalculo produce
        # session_mismatch -> esperado blocked; el resultado dice ok -> incoherente.
        with self.assertRaisesRegex(ValidationError, "outcome"):
            self.bind(expected_session_name="other")

    def test_wrong_command_rejected_as_incoherent(self):
        with self.assertRaisesRegex(ValidationError, "outcome"):
            self.bind(expected_command="other")

    def test_wrong_task_id_rejected(self):
        task = load("task-card-valid.json")
        result = load("preflight-result-ok.json")
        result = copy.deepcopy(result)
        result["task_id"] = "other-task"
        with self.assertRaisesRegex(ValidationError, "task_id"):
            self.bind(task=task, result=result)

    def _assert_adulterated_ok_rejected(self, **mutations):
        result = copy.deepcopy(load("preflight-result-ok.json"))
        for key, value in mutations.items():
            result["observed"][key] = value
        with self.assertRaisesRegex(ValidationError, "outcome"):
            self.bind(result=result)

    def test_binding_rejects_adulterated_ok_branch(self):
        self._assert_adulterated_ok_rejected(observed_branch="codex/other")

    def test_binding_rejects_adulterated_ok_sha(self):
        self._assert_adulterated_ok_rejected(observed_sha="0" * 40)

    def test_binding_rejects_adulterated_ok_dirty(self):
        self._assert_adulterated_ok_rejected(worktree_clean=False)

    def test_binding_rejects_adulterated_ok_pane_dead(self):
        self._assert_adulterated_ok_rejected(pane_alive=False)

    def test_binding_rejects_adulterated_ok_platform(self):
        self._assert_adulterated_ok_rejected(observed_platform="windows")

    def test_binding_accepts_blocked_session_mismatch(self):
        task = load("task-card-valid.json")
        adapter = load("adapter-capabilities-opencode-tmux.json")
        observations = load("run-context-ok.json")
        observations["observed_session_name"] = "other-session"
        result = evaluate_preflight(
            task, adapter, observations,
            expected_run_id=RUN_ID, expected_attempt_id=ATTEMPT_ID,
            expected_session_name=SESSION_NAME, expected_command=COMMAND,
        )
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reasons"], ["session_mismatch"])
        validate_preflight_binding(
            result, task, adapter, RUN_ID, ATTEMPT_ID, SESSION_NAME, COMMAND,
        )

    def test_binding_accepts_blocked_command_unexpected(self):
        task = load("task-card-valid.json")
        adapter = load("adapter-capabilities-opencode-tmux.json")
        observations = load("run-context-ok.json")
        observations["observed_command"] = "rm -rf /"
        result = evaluate_preflight(
            task, adapter, observations,
            expected_run_id=RUN_ID, expected_attempt_id=ATTEMPT_ID,
            expected_session_name=SESSION_NAME, expected_command=COMMAND,
        )
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reasons"], ["command_unexpected"])
        validate_preflight_binding(
            result, task, adapter, RUN_ID, ATTEMPT_ID, SESSION_NAME, COMMAND,
        )
