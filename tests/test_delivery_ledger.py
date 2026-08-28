import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from epistates.delivery_ledger import DeliveryLedgerStore


class DeliveryLedgerStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "delivery.sqlite"
        self.store = DeliveryLedgerStore(self.path)
        self.nonce = "a" * 32
        self.receipt_digest = "sha256:" + "b" * 64
        self.body_digest = "sha256:" + "c" * 64

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **changes):
        values = {
            "nonce": self.nonce,
            "receipt_digest": self.receipt_digest,
            "target_id": "target-one",
            "provider_id": "opencode-local",
            "provider_version": "1.18.23",
            "agent_id": "epistates-inspect",
            "model_id": "glm-5.2",
            "body_digest": self.body_digest,
            "observed_at": "2026-08-28T20:00:00Z",
        }
        values.update(changes)
        return self.store.create_reserved(**values)

    def transition(self, expected_state, new_state, second, **changes):
        values = {
            "nonce": self.nonce,
            "expected_state": expected_state,
            "new_state": new_state,
            "observed_at": f"2026-08-28T20:00:{second:02d}Z",
        }
        if new_state != "submitting":
            values.update({
                "result_class": f"{new_state}-evidence",
                "evidence_digest": "sha256:" + "d" * 64,
            })
        values.update(changes)
        return self.store.transition(**values)

    def test_full_lifecycle_and_history_survive_restart(self):
        self.assertEqual(self.create(), "reserved")
        self.assertEqual(self.transition("reserved", "submitting", 1), "updated")
        self.assertEqual(self.transition("submitting", "submitted", 2), "updated")
        self.assertEqual(self.transition("submitted", "completed", 3), "updated")

        restarted = DeliveryLedgerStore(self.path)
        attempt = restarted.get(self.nonce)
        self.assertEqual(attempt.state, "completed")
        self.assertEqual(attempt.body_digest, self.body_digest)
        events = restarted.history(self.nonce)
        self.assertEqual([event.to_state for event in events], [
            "reserved", "submitting", "submitted", "completed",
        ])
        self.assertEqual(events[0].from_state, None)
        self.assertEqual(events[-1].result_class, "completed-evidence")

    def test_exact_creation_replay_is_idempotent_but_collisions_fail(self):
        self.assertEqual(self.create(), "reserved")
        self.assertEqual(self.create(), "reserved")
        self.assertEqual(len(self.store.history(self.nonce)), 1)
        self.assertEqual(self.create(target_id="target-two"), "duplicate")
        self.assertEqual(self.create(nonce="e" * 32), "duplicate")

    def test_submitting_crash_window_survives_and_becomes_ambiguous(self):
        self.assertEqual(self.create(), "reserved")
        self.assertEqual(self.transition("reserved", "submitting", 1), "updated")
        restarted = DeliveryLedgerStore(self.path)
        self.assertEqual(restarted.get(self.nonce).state, "submitting")
        self.store = restarted
        self.assertEqual(self.transition("submitting", "ambiguous", 2), "updated")
        self.assertEqual(self.store.get(self.nonce).state, "ambiguous")
        self.assertEqual(self.transition("ambiguous", "submitted", 3), "invalid")

    def test_submitted_is_not_completed_and_terminal_states_are_immutable(self):
        self.assertEqual(self.create(), "reserved")
        self.assertEqual(self.transition("reserved", "submitting", 1), "updated")
        self.assertEqual(self.transition("submitting", "submitted", 2), "updated")
        self.assertEqual(self.store.get(self.nonce).state, "submitted")
        self.assertEqual(self.transition("submitted", "failed", 3), "updated")
        self.assertEqual(self.transition("failed", "completed", 4), "invalid")

    def test_skips_and_backwards_transitions_are_rejected(self):
        self.assertEqual(self.create(), "reserved")
        self.assertEqual(self.transition("reserved", "submitted", 1), "invalid")
        self.assertEqual(self.transition("reserved", "completed", 1), "invalid")
        self.assertEqual(self.transition("reserved", "submitting", 1), "updated")
        self.assertEqual(self.transition("submitting", "reserved", 2), "invalid")

    def test_evidence_and_monotonic_timestamp_are_required(self):
        self.assertEqual(self.create(), "reserved")
        self.assertEqual(self.transition(
            "reserved", "submitting", 1,
            evidence_digest="sha256:" + "d" * 64,
        ), "invalid")
        self.assertEqual(self.transition("reserved", "submitting", 1), "updated")
        self.assertEqual(self.transition(
            "submitting", "submitted", 2,
            result_class=None, evidence_digest=None,
        ), "invalid")
        self.assertEqual(self.transition("submitting", "submitted", 0), "invalid")

    def test_concurrent_cas_has_exactly_one_winner(self):
        self.assertEqual(self.create(), "reserved")
        outcomes = []
        lock = threading.Lock()

        def update(new_state):
            result = self.store.transition(
                nonce=self.nonce,
                expected_state="reserved",
                new_state=new_state,
                observed_at="2026-08-28T20:00:01Z",
                result_class="local-failure" if new_state == "failed" else None,
                evidence_digest="sha256:" + "e" * 64 if new_state == "failed" else None,
            )
            with lock:
                outcomes.append(result)

        threads = [
            threading.Thread(target=update, args=("submitting",)),
            threading.Thread(target=update, args=("failed",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("updated"), 1)
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(len(self.store.history(self.nonce)), 2)

    def test_invalid_input_missing_attempt_and_corruption_fail_closed(self):
        self.assertEqual(self.create(nonce="bad"), "invalid")
        self.assertEqual(self.create(body_digest="secret prompt"), "invalid")
        self.assertEqual(self.transition("reserved", "submitting", 1), "not_found")

        corrupt = Path(self.tmp.name) / "corrupt.sqlite"
        corrupt.write_bytes(b"not sqlite")
        disabled = DeliveryLedgerStore(corrupt)
        self.assertEqual(disabled.create_reserved(
            nonce=self.nonce,
            receipt_digest=self.receipt_digest,
            target_id="target-one",
            provider_id="opencode-local",
            provider_version="1.18.23",
            agent_id="epistates-inspect",
            model_id="glm-5.2",
            body_digest=self.body_digest,
            observed_at="2026-08-28T20:00:00Z",
        ), "disabled")

    def test_unknown_schema_version_disables_store(self):
        schema_path = Path(self.tmp.name) / "future.sqlite"
        with sqlite3.connect(schema_path) as db:
            db.execute("CREATE TABLE delivery_meta (id INTEGER PRIMARY KEY, schema_version INTEGER)")
            db.execute("INSERT INTO delivery_meta VALUES(1, 999)")
        disabled = DeliveryLedgerStore(schema_path)
        with sqlite3.connect(schema_path) as db:
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertEqual(tables, {"delivery_meta"})
        self.assertEqual(disabled.create_reserved(
            nonce=self.nonce,
            receipt_digest=self.receipt_digest,
            target_id="target-one",
            provider_id="opencode-local",
            provider_version="1.18.23",
            agent_id="epistates-inspect",
            model_id="glm-5.2",
            body_digest=self.body_digest,
            observed_at="2026-08-28T20:00:00Z",
        ), "disabled")


if __name__ == "__main__":
    unittest.main()
