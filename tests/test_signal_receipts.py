import tempfile
import threading
import unittest
from pathlib import Path

from epistates.signal_receipts import SignalReceiptStore


def context(**changes):
    value = {"task_id": "task-one", "run_id": "run-one", "attempt_id": "attempt-one", "adapter_id": "opencode-tmux", "session_name": "session-one", "dispatch_receipt_digest": "sha256:" + "a" * 64, "event_type": "external_completion", "dispatched_at": "2026-08-28T17:00:00Z"}
    value.update(changes)
    return value


class SignalReceiptStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SignalReceiptStore(Path(self.tmp.name) / "receipts.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def consume(self, **kwargs):
        return self.store.consume_once(context(), observed_at="2026-08-28T17:01:00Z", ttl_seconds=120, **kwargs)

    def test_first_is_accepted_then_duplicate(self):
        self.assertEqual(self.consume(), "accepted")
        self.assertEqual(self.consume(), "duplicate")

    def test_expired_and_kill_switch_have_no_consumption(self):
        self.assertEqual(self.store.consume_once(context(), observed_at="2026-08-28T17:03:01Z", ttl_seconds=120), "expired")
        self.assertEqual(self.consume(kill_switch=True), "disabled")
        self.assertEqual(self.consume(), "accepted")

    def test_invalid_context_is_rejected(self):
        self.assertEqual(self.store.consume_once({"task_id": "x"}, observed_at="2026-08-28T17:01:00Z", ttl_seconds=120), "invalid")

    def test_corrupt_store_is_disabled(self):
        path = Path(self.tmp.name) / "corrupt.sqlite"
        path.write_bytes(b"not sqlite")
        self.assertEqual(SignalReceiptStore(path).consume_once(context(), observed_at="2026-08-28T17:01:00Z", ttl_seconds=120), "disabled")

    def test_concurrent_consumers_have_one_winner(self):
        outcomes = []
        lock = threading.Lock()
        def run():
            result = self.consume()
            with lock:
                outcomes.append(result)
        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(outcomes.count("accepted"), 1)
        self.assertEqual(outcomes.count("duplicate"), 3)
