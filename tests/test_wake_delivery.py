import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from epistates.delivery_ledger import DeliveryLedgerStore
from epistates.opencode_wake import OpenCodeWakePort
from epistates.wake_delivery import WakeDeliveryCoordinator, WakeSubmissionCoordinator
from epistates.wake_guard import WakeGuardStore


class WakeDeliveryCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "shared.sqlite"
        self.guard = WakeGuardStore(
            self.path, enabled=True, global_limit=2, target_limit=1,
        )
        self.ledger = DeliveryLedgerStore(self.path)
        self.coordinator = WakeDeliveryCoordinator(self.guard, self.ledger)

    def tearDown(self):
        self.tmp.cleanup()

    def values(self, **changes):
        values = {
            "receipt_digest": "sha256:" + "a" * 64,
            "target_id": "target-one",
            "nonce": "b" * 32,
            "dispatched_at": "2026-08-28T19:59:00Z",
            "observed_at": "2026-08-28T20:00:00Z",
            "ttl_seconds": 120,
            "provider_id": "opencode-local",
            "provider_version": "1.18.23",
            "agent_id": "epistates-inspect",
            "model_id": "glm-5.2",
            "body_digest": "sha256:" + "c" * 64,
        }
        values.update(changes)
        return values

    def wake_count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT COUNT(*) FROM wake_reservations").fetchone()[0]

    def test_atomic_reservation_survives_restart_without_advancing_delivery(self):
        self.assertEqual(self.coordinator.reserve(**self.values()), "reserved")
        self.assertEqual(self.wake_count(), 1)

        restarted_guard = WakeGuardStore(
            self.path, enabled=True, global_limit=2, target_limit=1,
        )
        restarted = DeliveryLedgerStore(self.path)
        restarted_coordinator = WakeDeliveryCoordinator(restarted_guard, restarted)
        attempt = restarted.get("b" * 32)
        self.assertEqual(attempt.state, "reserved")
        self.assertEqual(attempt.receipt_digest, "sha256:" + "a" * 64)
        self.assertEqual([event.to_state for event in restarted.history("b" * 32)], ["reserved"])
        self.assertEqual(restarted_coordinator.reserve(**self.values()), "duplicate")
        self.assertEqual(len(restarted.history("b" * 32)), 1)

    def test_delivery_insert_failure_rolls_back_guard_and_clock(self):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TRIGGER reject_delivery BEFORE INSERT ON delivery_attempts "
                "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        self.assertEqual(self.coordinator.reserve(**self.values()), "disabled")
        self.assertEqual(self.wake_count(), 0)
        with sqlite3.connect(self.path) as db:
            last = db.execute(
                "SELECT last_observed_at FROM wake_policy WHERE id=1"
            ).fetchone()[0]
        self.assertIsNone(last)

    def test_rate_limit_and_kill_switch_never_create_delivery(self):
        self.assertEqual(self.coordinator.reserve(**self.values()), "reserved")
        second = self.values(
            receipt_digest="sha256:" + "d" * 64,
            nonce="e" * 32,
            body_digest="sha256:" + "f" * 64,
        )
        self.assertEqual(self.coordinator.reserve(**second), "rate_limited")
        self.assertIsNone(self.ledger.get("e" * 32))

        other_path = Path(self.tmp.name) / "killed.sqlite"
        guard = WakeGuardStore(other_path, enabled=True)
        ledger = DeliveryLedgerStore(other_path)
        coordinator = WakeDeliveryCoordinator(guard, ledger)
        self.assertEqual(guard.activate_kill_switch(), "disabled")
        self.assertEqual(coordinator.reserve(**self.values()), "disabled")
        self.assertIsNone(ledger.get("b" * 32))

    def test_preexisting_delivery_collision_rolls_back_new_guard_reservation(self):
        self.assertEqual(self.ledger.create_reserved(
            nonce="b" * 32,
            receipt_digest="sha256:" + "a" * 64,
            target_id="target-one",
            provider_id="opencode-local",
            provider_version="1.18.23",
            agent_id="epistates-inspect",
            model_id="glm-5.2",
            body_digest="sha256:" + "c" * 64,
            observed_at="2026-08-28T20:00:00Z",
        ), "reserved")
        self.assertEqual(self.coordinator.reserve(**self.values()), "duplicate")
        self.assertEqual(self.wake_count(), 0)
        self.assertEqual(len(self.ledger.history("b" * 32)), 1)

    def test_invalid_delivery_input_never_consumes_quota(self):
        self.assertEqual(self.coordinator.reserve(
            **self.values(body_digest="plain prompt")
        ), "invalid")
        self.assertEqual(self.wake_count(), 0)

    def test_different_database_paths_fail_closed(self):
        other = DeliveryLedgerStore(Path(self.tmp.name) / "other.sqlite")
        coordinator = WakeDeliveryCoordinator(self.guard, other)
        self.assertEqual(coordinator.reserve(**self.values()), "disabled")
        self.assertEqual(self.wake_count(), 0)

    def test_concurrent_global_limit_has_one_atomic_winner(self):
        path = Path(self.tmp.name) / "concurrent.sqlite"
        guard = WakeGuardStore(path, enabled=True, global_limit=1, target_limit=1)
        ledger = DeliveryLedgerStore(path)
        coordinator = WakeDeliveryCoordinator(guard, ledger)
        outcomes = []
        lock = threading.Lock()

        def reserve(index):
            marker = "1" if index == 0 else "2"
            result = coordinator.reserve(**self.values(
                receipt_digest="sha256:" + marker * 64,
                target_id=f"target-{marker}",
                nonce=marker * 32,
                body_digest="sha256:" + ("3" if index == 0 else "4") * 64,
            ))
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=reserve, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("reserved"), 1)
        self.assertEqual(outcomes.count("rate_limited"), 1)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wake_reservations").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM delivery_attempts").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM delivery_events").fetchone()[0], 1)


class FakeWakePort:
    def __init__(self, binding, result="queued", *, raises=False):
        self._binding = dict(binding)
        self.result = result
        self.raises = raises
        self.calls = []

    def delivery_binding(self, nonce):
        return dict(self._binding)

    def request_wake(self, session_id, nonce):
        self.calls.append((session_id, nonce))
        if self.raises:
            raise OSError("resultado incierto")
        return self.result


class WakeSubmissionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "submission.sqlite"
        self.guard = WakeGuardStore(
            self.path, enabled=True, global_limit=10, target_limit=10,
        )
        self.ledger = DeliveryLedgerStore(self.path)
        self.nonce = "a" * 32
        self.binding = {
            "provider_id": "opencode-local",
            "provider_version": "1.18.23",
            "agent_id": "epistates-inspect",
            "model_id": "glm-5.2",
            "body_digest": "sha256:" + "c" * 64,
        }
        reserve = WakeDeliveryCoordinator(self.guard, self.ledger).reserve(
            receipt_digest="sha256:" + "b" * 64,
            target_id="ses-one", nonce=self.nonce,
            dispatched_at="2026-08-28T20:00:00Z",
            observed_at="2026-08-28T20:00:01Z", ttl_seconds=60,
            **self.binding,
        )
        self.assertEqual(reserve, "reserved")

    def tearDown(self):
        self.tmp.cleanup()

    def coordinator(self, result="queued", *, raises=False, binding=None,
                    guard=None, ledger=None):
        port = FakeWakePort(binding or self.binding, result, raises=raises)
        coordinator = WakeSubmissionCoordinator(
            guard or self.guard, ledger or self.ledger, port,
        )
        return coordinator, port

    def submit(self, coordinator):
        return coordinator.submit(
            nonce=self.nonce, observed_at="2026-08-28T20:00:02Z",
        )

    def test_queued_becomes_submitted_with_one_call_and_history(self):
        coordinator, port = self.coordinator()
        self.assertEqual(self.submit(coordinator), "submitted")
        self.assertEqual(port.calls, [("ses-one", self.nonce)])
        self.assertEqual(self.ledger.get(self.nonce).state, "submitted")
        events = self.ledger.history(self.nonce)
        self.assertEqual([event.to_state for event in events],
                         ["reserved", "submitting", "submitted"])
        self.assertEqual(events[-1].result_class, "provider-queued")

    def test_known_pre_effect_results_fail_and_uncertain_results_ambiguous(self):
        for result, expected in (("unsupported", "failed"),
                                 ("rejected", "failed"),
                                 ("failed", "ambiguous"),
                                 ({"unexpected": True}, "ambiguous")):
            with self.subTest(result=result):
                path = Path(self.tmp.name) / (str(len(str(result))) + ".sqlite")
                guard = WakeGuardStore(path, enabled=True, global_limit=10,
                                       target_limit=10)
                ledger = DeliveryLedgerStore(path)
                nonce = ("d" if result != "rejected" else "e") * 32
                values = dict(self.binding)
                self.assertEqual(WakeDeliveryCoordinator(guard, ledger).reserve(
                    receipt_digest="sha256:" + nonce[0] * 64,
                    target_id="ses-two", nonce=nonce,
                    dispatched_at="2026-08-28T20:00:00Z",
                    observed_at="2026-08-28T20:00:01Z", ttl_seconds=60,
                    **values,
                ), "reserved")
                port = FakeWakePort(values, result)
                outcome = WakeSubmissionCoordinator(guard, ledger, port).submit(
                    nonce=nonce, observed_at="2026-08-28T20:00:02Z")
                self.assertEqual(outcome, expected)
                self.assertEqual(ledger.get(nonce).state, expected)

    def test_hostile_result_object_becomes_ambiguous_without_escape(self):
        class HostileResult:
            def __eq__(self, other):
                raise RuntimeError("comparación hostil")

        coordinator, port = self.coordinator(result=HostileResult())
        self.assertEqual(self.submit(coordinator), "ambiguous")
        self.assertEqual(port.calls, [("ses-one", self.nonce)])
        self.assertEqual(self.ledger.get(self.nonce).state, "ambiguous")

    def test_exception_is_ambiguous_and_never_retried(self):
        coordinator, port = self.coordinator(raises=True)
        self.assertEqual(self.submit(coordinator), "ambiguous")
        self.assertEqual(port.calls, [("ses-one", self.nonce)])
        self.assertEqual(self.submit(coordinator), "conflict")
        self.assertEqual(port.calls, [("ses-one", self.nonce)])

    def test_kill_switch_between_cas_and_port_fails_without_call(self):
        guard = self.guard

        class SwitchingGuard(WakeGuardStore):
            def __init__(self, original):
                self.__dict__ = original.__dict__
                self.confirmations = 0

            def confirm_submission(self, **values):
                self.confirmations += 1
                if self.confirmations == 2:
                    self.activate_kill_switch()
                return super().confirm_submission(**values)

        switching = SwitchingGuard(guard)
        coordinator, port = self.coordinator(guard=switching)
        self.assertEqual(self.submit(coordinator), "failed")
        self.assertEqual(port.calls, [])
        self.assertEqual(self.ledger.get(self.nonce).state, "failed")

    def test_binding_mismatch_or_missing_reservation_never_calls(self):
        bad = dict(self.binding, model_id="glm-other")
        coordinator, port = self.coordinator(binding=bad)
        self.assertEqual(self.submit(coordinator), "mismatch")
        self.assertEqual(port.calls, [])
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM wake_reservations")
        coordinator, port = self.coordinator()
        self.assertEqual(self.submit(coordinator), "not_found")
        self.assertEqual(port.calls, [])

    def test_invalid_guard_binding_fails_closed_without_exception(self):
        self.assertEqual(self.guard.confirm_submission(
            nonce=None, receipt_digest="sha256:" + "b" * 64,
            target_id="ses-one",
        ), "invalid")

    def test_real_port_shape_with_fake_transport_integrates(self):
        calls = []

        def transport(method, path, body):
            calls.append((method, path, body))
            if path == "/global/health":
                return {"healthy": True, "version": "1.18.25"}
            if path == "/agent":
                return [{
                    "name": "epistates-inspect", "mode": "primary",
                    "model": {"providerID": "zai", "modelID": "glm-5.2"},
                    "permission": [
                        {"permission": "*", "pattern": "*", "action": "deny"},
                        {"permission": "external_directory", "pattern": "*", "action": "deny"},
                        {"permission": "external_directory",
                         "pattern": "/Users/test/.local/share/opencode/tool-output/*",
                         "action": "allow"},
                    ],
                }]
            if path.endswith("/prompt_async"):
                return None
            raise AssertionError(path)

        port = OpenCodeWakePort(
            "http://127.0.0.1:4096", provider_version="1.18.25",
            agent_id="epistates-inspect", model_id="glm-5.2",
            transport=transport,
        )
        other_path = Path(self.tmp.name) / "real-port-shape.sqlite"
        guard = WakeGuardStore(other_path, enabled=True)
        ledger = DeliveryLedgerStore(other_path)
        binding = port.delivery_binding("f" * 32)
        self.assertEqual(WakeDeliveryCoordinator(guard, ledger).reserve(
            receipt_digest="sha256:" + "f" * 64,
            target_id="ses-real", nonce="f" * 32,
            dispatched_at="2026-08-28T20:00:00Z",
            observed_at="2026-08-28T20:00:01Z", ttl_seconds=60,
            **binding,
        ), "reserved")
        outcome = WakeSubmissionCoordinator(guard, ledger, port).submit(
            nonce="f" * 32, observed_at="2026-08-28T20:00:02Z")
        self.assertEqual(outcome, "submitted")
        self.assertEqual(sum(method == "POST" for method, _, _ in calls), 1)

    def test_two_callers_produce_exactly_one_port_call(self):
        coordinator, port = self.coordinator()
        outcomes = []
        lock = threading.Lock()

        def submit():
            outcome = self.submit(coordinator)
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(port.calls), 1)
        self.assertIn("submitted", outcomes)
        self.assertEqual(sum(value in {"conflict", "ambiguous"}
                             for value in outcomes), 1)

    def test_failure_persisting_ack_leaves_submitting_and_reports_ambiguous(self):
        coordinator, port = self.coordinator()
        original = self.ledger.transition

        def transition(**values):
            if values["new_state"] == "submitted":
                return "disabled"
            return original(**values)

        self.ledger.transition = transition
        self.assertEqual(self.submit(coordinator), "ambiguous")
        self.assertEqual(port.calls, [("ses-one", self.nonce)])
        restarted = DeliveryLedgerStore(self.path)
        self.assertEqual(restarted.get(self.nonce).state, "submitting")
        again, another_port = self.coordinator(ledger=restarted)
        self.assertEqual(self.submit(again), "conflict")
        self.assertEqual(another_port.calls, [])


if __name__ == "__main__":
    unittest.main()
