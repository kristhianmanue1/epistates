import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from epistates.delivery_ledger import DeliveryLedgerStore
from epistates.wake_delivery import WakeDeliveryCoordinator
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


if __name__ == "__main__":
    unittest.main()
