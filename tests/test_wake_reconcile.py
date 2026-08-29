import ast
import inspect
import tempfile
import threading
import unittest
from pathlib import Path

from epistates.delivery_ledger import DeliveryLedgerStore
import epistates.wake_reconcile as wake_reconcile
from epistates.wake_reconcile import (
    TerminalObservation,
    TerminalObserver,
    WakeTerminalReconciler,
)


class FakeObserver:
    def __init__(self, binding, observation=None, *, raises=False, barrier=None):
        self.binding = dict(binding)
        self.observation = observation
        self.raises = raises
        self.barrier = barrier
        self.calls = []

    def delivery_binding(self, nonce):
        return dict(self.binding)

    def observe(self, target_id, nonce):
        self.calls.append(target_id)
        if self.barrier is not None:
            self.barrier.wait()
        if self.raises:
            raise OSError("lectura incierta")
        return self.observation


class WakeTerminalReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "reconcile.sqlite"
        self.store = DeliveryLedgerStore(self.path)
        self.nonce = "a" * 32
        self.binding = {
            "provider_id": "opencode-local",
            "provider_version": "1.18.23",
            "agent_id": "epistates-inspect",
            "model_id": "glm-5.2",
            "body_digest": "sha256:" + "b" * 64,
        }
        self.assertEqual(self.store.create_reserved(
            nonce=self.nonce, receipt_digest="sha256:" + "c" * 64,
            target_id="ses-one", observed_at="2026-08-28T20:00:00Z",
            **self.binding,
        ), "reserved")

    def tearDown(self):
        self.tmp.cleanup()

    def to_submitting(self):
        self.assertEqual(self.store.transition(
            nonce=self.nonce, expected_state="reserved", new_state="submitting",
            observed_at="2026-08-28T20:00:01Z",
        ), "updated")

    def to_submitted(self):
        self.to_submitting()
        self.assertEqual(self.store.transition(
            nonce=self.nonce, expected_state="submitting", new_state="submitted",
            observed_at="2026-08-28T20:00:02Z",
            result_class="provider-queued",
            evidence_digest="sha256:" + "d" * 64,
        ), "updated")

    def observation(self, outcome="completed", *, terminal=True,
                    text=True, tools=False, target_id="ses-one",
                    body_digest=None):
        return TerminalObservation(
            target_id=target_id,
            body_digest=body_digest or self.binding["body_digest"],
            outcome=outcome, terminal=terminal,
            has_nonempty_text=text, has_tool_parts=tools,
            evidence_digest="sha256:" + "e" * 64,
        )

    def reconcile(self, observer, second=3):
        return WakeTerminalReconciler(self.store, observer).reconcile(
            nonce=self.nonce, observed_at=f"2026-08-28T20:00:0{second}Z",
        )

    def test_submitting_restart_becomes_ambiguous_without_observer_call(self):
        self.to_submitting()
        restarted = DeliveryLedgerStore(self.path)
        observer = FakeObserver(self.binding, self.observation())
        outcome = WakeTerminalReconciler(restarted, observer).reconcile(
            nonce=self.nonce, observed_at="2026-08-28T20:00:03Z")
        self.assertEqual(outcome, "ambiguous")
        self.assertEqual(observer.calls, [])
        self.assertEqual(restarted.get(self.nonce).state, "ambiguous")

    def test_pending_keeps_submitted_and_can_be_observed_later(self):
        self.to_submitted()
        observer = FakeObserver(
            self.binding, self.observation("pending", terminal=False, text=False))
        self.assertEqual(self.reconcile(observer), "pending")
        self.assertEqual(self.store.get(self.nonce).state, "submitted")
        self.assertEqual(len(self.store.history(self.nonce)), 3)

    def test_terminal_nonempty_without_tools_completes(self):
        self.to_submitted()
        observer = FakeObserver(self.binding, self.observation())
        self.assertEqual(self.reconcile(observer), "completed")
        self.assertEqual(self.store.get(self.nonce).state, "completed")
        self.assertEqual(self.store.history(self.nonce)[-1].result_class,
                         "provider-terminal-completed")

    def test_explicit_terminal_failure_fails(self):
        self.to_submitted()
        observer = FakeObserver(
            self.binding, self.observation("failed", text=False))
        self.assertEqual(self.reconcile(observer), "failed")
        self.assertEqual(self.store.get(self.nonce).state, "failed")

    def test_tool_part_fails_even_with_text(self):
        self.to_submitted()
        observer = FakeObserver(self.binding, self.observation(tools=True))
        self.assertEqual(self.reconcile(observer), "failed")
        self.assertEqual(self.store.history(self.nonce)[-1].result_class,
                         "provider-tool-part")

    def test_tool_part_dominates_pending_claim(self):
        self.to_submitted()
        observer = FakeObserver(
            self.binding,
            self.observation("pending", terminal=False, text=False, tools=True),
        )
        self.assertEqual(self.reconcile(observer), "failed")
        self.assertEqual(self.store.history(self.nonce)[-1].result_class,
                         "provider-tool-part")

    def test_terminal_empty_and_cross_binding_are_ambiguous(self):
        for observation, expected_class in (
                (self.observation(text=False), "provider-terminal-empty"),
                (self.observation(target_id="ses-other"),
                 "provider-binding-mismatch")):
            with self.subTest(result_class=expected_class):
                path = Path(self.tmp.name) / (expected_class + ".sqlite")
                store = DeliveryLedgerStore(path)
                self.store = store
                self.setUp_attempt_only()
                self.to_submitted()
                observer = FakeObserver(self.binding, observation)
                self.assertEqual(self.reconcile(observer), "ambiguous")
                self.assertEqual(store.history(self.nonce)[-1].result_class,
                                 expected_class)

    def setUp_attempt_only(self):
        self.assertEqual(self.store.create_reserved(
            nonce=self.nonce, receipt_digest="sha256:" + "c" * 64,
            target_id="ses-one", observed_at="2026-08-28T20:00:00Z",
            **self.binding,
        ), "reserved")

    def test_invalid_or_raising_observation_is_ambiguous(self):
        for observer in (FakeObserver(self.binding, {"status": "done"}),
                         FakeObserver(self.binding, raises=True)):
            with self.subTest(raises=observer.raises):
                path = Path(self.tmp.name) / ("raise" if observer.raises else "invalid")
                self.store = DeliveryLedgerStore(path)
                self.setUp_attempt_only()
                self.to_submitted()
                self.assertEqual(self.reconcile(observer), "ambiguous")
                self.assertEqual(self.store.get(self.nonce).state, "ambiguous")

    def test_observer_binding_mismatch_does_not_observe_or_transition(self):
        self.to_submitted()
        observer = FakeObserver(dict(self.binding, model_id="glm-other"),
                                self.observation())
        self.assertEqual(self.reconcile(observer), "mismatch")
        self.assertEqual(observer.calls, [])
        self.assertEqual(self.store.get(self.nonce).state, "submitted")

    def test_terminal_and_reserved_states_do_not_observe(self):
        observer = FakeObserver(self.binding, self.observation())
        self.assertEqual(self.reconcile(observer), "conflict")
        self.assertEqual(observer.calls, [])
        self.to_submitting()
        self.assertEqual(self.store.transition(
            nonce=self.nonce, expected_state="submitting", new_state="ambiguous",
            observed_at="2026-08-28T20:00:02Z",
            result_class="manual-ambiguous",
            evidence_digest="sha256:" + "f" * 64,
        ), "updated")
        self.assertEqual(self.reconcile(observer), "ambiguous")
        self.assertEqual(observer.calls, [])

    def test_two_reconcilers_may_read_but_only_one_terminal_cas_wins(self):
        self.to_submitted()
        barrier = threading.Barrier(2)
        observer = FakeObserver(self.binding, self.observation(), barrier=barrier)
        outcomes = []
        lock = threading.Lock()

        def reconcile():
            result = self.reconcile(observer)
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=reconcile) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(observer.calls, ["ses-one", "ses-one"])
        self.assertEqual(outcomes.count("completed"), 1)
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(self.store.get(self.nonce).state, "completed")
        self.assertEqual(len(self.store.history(self.nonce)), 4)

    def test_module_and_observer_expose_no_transport_or_send_capability(self):
        source = inspect.getsource(wake_reconcile)
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint({
            "httpx", "requests", "socket", "subprocess", "urllib",
        }))
        self.assertNotIn("request_wake", TerminalObserver.__dict__)
        self.assertNotIn("send", TerminalObserver.__dict__)


if __name__ == "__main__":
    unittest.main()
