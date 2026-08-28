import json
import tempfile
import unittest
from pathlib import Path

from epistates.signal_inbox import LocalSignalInbox
from epistates.signal_receipts import SignalReceiptStore


def context():
    return {"task_id":"task-one","run_id":"run-one","attempt_id":"attempt-one","adapter_id":"opencode-tmux","session_name":"session-one","dispatch_receipt_digest":"sha256:"+"a"*64,"event_type":"external_completion","dispatched_at":"2026-08-28T17:00:00Z","current_state":"WAITING_EXTERNAL"}


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name) / "inbox"; self.root.mkdir()
        self.inbox = LocalSignalInbox(self.root, SignalReceiptStore(Path(self.tmp.name) / "store.sqlite"))
    def tearDown(self): self.tmp.cleanup()
    def test_reconciles_once_without_wake(self):
        (self.root / "event.json").write_text(json.dumps(context()), encoding="utf-8")
        self.assertEqual(self.inbox.reconcile(observed_at="2026-08-28T17:01:00Z", ttl_seconds=120), ["accepted"])
        self.assertFalse((self.root / "event.json").exists())
    def test_rejects_oversized_and_invalid_json(self):
        (self.root / "big").write_bytes(b"x" * 5000); (self.root / "bad").write_text("{", encoding="utf-8")
        self.assertEqual(self.inbox.reconcile(observed_at="2026-08-28T17:01:00Z", ttl_seconds=120), ["invalid", "invalid"])
    def test_rejects_symlink_without_consuming_target(self):
        target = self.root / "target.json"; target.write_text(json.dumps(context()), encoding="utf-8")
        (self.root / "link.json").symlink_to(target.name)
        self.assertEqual(self.inbox.reconcile(observed_at="2026-08-28T17:01:00Z", ttl_seconds=120), ["invalid", "accepted"])
    def test_quarantine_prevents_invalid_starvation(self):
        self.inbox.max_files = 1
        (self.root / "00-bad").write_text("{", encoding="utf-8")
        (self.root / "99-good").write_text(json.dumps(context()), encoding="utf-8")
        self.assertEqual(self.inbox.reconcile(observed_at="2026-08-28T17:01:00Z", ttl_seconds=120), ["invalid"])
        self.assertEqual(self.inbox.reconcile(observed_at="2026-08-28T17:01:00Z", ttl_seconds=120), ["accepted"])
