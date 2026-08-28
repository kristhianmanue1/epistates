import tempfile
import threading
import unittest
from pathlib import Path

from epistates.wake_guard import WakeGuardStore


class WakeGuardStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "wake.sqlite"
        self.store = WakeGuardStore(self.path, enabled=True, global_limit=2, target_limit=1)

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, **changes):
        value = {"receipt_digest": "sha256:" + "a" * 64, "target_id": "target-one", "nonce": "b" * 32, "dispatched_at": "2026-08-28T17:59:00Z", "observed_at": "2026-08-28T18:00:00Z", "ttl_seconds": 120}
        value.update(changes)
        return self.store.reserve(**value)

    def test_reserves_once_and_survives_restart(self):
        self.assertEqual(self.reserve(), "reserved")
        restarted = WakeGuardStore(self.path, enabled=True, global_limit=2, target_limit=1)
        self.assertEqual(restarted.reserve(receipt_digest="sha256:" + "a" * 64, target_id="target-one", nonce="c" * 32, dispatched_at="2026-08-28T17:59:00Z", observed_at="2026-08-28T18:00:00Z", ttl_seconds=120), "duplicate")

    def test_disabled_policy_and_persistent_kill_switch_fail_closed(self):
        disabled = WakeGuardStore(Path(self.tmp.name) / "off.sqlite")
        self.assertEqual(disabled.reserve(receipt_digest="sha256:" + "a" * 64, target_id="target-one", nonce="b" * 32, dispatched_at="2026-08-28T17:59:00Z", observed_at="2026-08-28T18:00:00Z", ttl_seconds=120), "disabled")
        self.assertEqual(self.store.activate_kill_switch(), "disabled")
        self.assertEqual(self.reserve(), "disabled")
        self.assertEqual(WakeGuardStore(self.path, enabled=True, global_limit=2, target_limit=1).reserve(receipt_digest="sha256:" + "a" * 64, target_id="target-one", nonce="b" * 32, dispatched_at="2026-08-28T17:59:00Z", observed_at="2026-08-28T18:00:00Z", ttl_seconds=120), "disabled")

    def test_rate_limit_and_clock_regression_do_not_reserve(self):
        self.assertEqual(self.reserve(), "reserved")
        self.assertEqual(self.reserve(receipt_digest="sha256:" + "c" * 64, nonce="d" * 32), "rate_limited")
        self.assertEqual(self.reserve(receipt_digest="sha256:" + "d" * 64, target_id="target-two", nonce="e" * 32, observed_at="2026-08-28T17:58:00Z"), "expired")

    def test_invalid_input_and_config_mismatch_fail_closed(self):
        self.assertEqual(self.reserve(nonce="bad"), "invalid")
        mismatch = WakeGuardStore(self.path, enabled=True, global_limit=3, target_limit=1)
        self.assertEqual(mismatch.reserve(receipt_digest="sha256:" + "a" * 64, target_id="target-one", nonce="b" * 32, dispatched_at="2026-08-28T17:59:00Z", observed_at="2026-08-28T18:00:00Z", ttl_seconds=120), "disabled")

    def test_corrupt_store_is_disabled(self):
        corrupt = Path(self.tmp.name) / "corrupt.sqlite"
        corrupt.write_bytes(b"not sqlite")
        self.assertEqual(WakeGuardStore(corrupt, enabled=True).reserve(receipt_digest="sha256:" + "a" * 64, target_id="target-one", nonce="b" * 32, dispatched_at="2026-08-28T17:59:00Z", observed_at="2026-08-28T18:00:00Z", ttl_seconds=120), "disabled")

    def test_concurrent_reservations_have_one_target_winner(self):
        outcomes, lock = [], threading.Lock()
        def reserve(index):
            result = self.store.reserve(receipt_digest="sha256:" + ("a" if index == 0 else "c") * 64, target_id="target-one", nonce=("b" if index == 0 else "d") * 32, dispatched_at="2026-08-28T17:59:00Z", observed_at="2026-08-28T18:00:00Z", ttl_seconds=120)
            with lock:
                outcomes.append(result)
        threads = [threading.Thread(target=reserve, args=(index,)) for index in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(outcomes.count("reserved"), 1)
        self.assertEqual(outcomes.count("rate_limited"), 1)
