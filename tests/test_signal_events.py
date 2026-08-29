import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from epistates.signal_events import KqueueSignalAdapter, SignalEventError


class FakeKqueue:
    def __init__(self, responses):
        self.responses = list(responses)
        self.controls = []
        self.closed = False

    def control(self, changes, max_events, timeout):
        self.controls.append((changes, max_events, timeout))
        if changes is not None:
            return []
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class KqueueSignalAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "inbox"
        self.root.mkdir()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def adapter(self, responses):
        self.fake = FakeKqueue(responses)
        return patch(
            "epistates.signal_events.select.kqueue",
            return_value=self.fake,
            create=True,
        ), patch.multiple(
            "epistates.signal_events.select",
            kevent=Mock(return_value=object()),
            KQ_FILTER_VNODE=1,
            KQ_EV_ADD=2,
            KQ_EV_CLEAR=4,
            KQ_NOTE_WRITE=8,
            KQ_NOTE_RENAME=16,
            KQ_NOTE_DELETE=32,
            KQ_NOTE_REVOKE=64,
            create=True,
        )

    def test_event_is_only_a_hint_and_discards_reconcile_result(self):
        kqueue, kevent = self.adapter([[object()]])
        def reconcile():
            self.calls.append("called")
            return False

        with kqueue, kevent, KqueueSignalAdapter(self.root, reconcile) as adapter:
            self.assertTrue(adapter.wait_once(0))
        self.assertEqual(self.calls, ["called"])
        self.assertEqual(self.fake.controls[1][1], 1)

    def test_timeout_or_lost_event_does_not_replace_startup_reconciliation(self):
        kqueue, kevent = self.adapter([[]])
        with kqueue, kevent, KqueueSignalAdapter(self.root, lambda: self.calls.append("event")) as adapter:
            self.assertFalse(adapter.wait_once(0))
        self.assertEqual(self.calls, [])

    def test_coalesced_or_flooded_events_reconcile_once_per_wait(self):
        kqueue, kevent = self.adapter([[object(), object(), object()]])
        with kqueue, kevent, KqueueSignalAdapter(self.root, lambda: self.calls.append("reconcile")) as adapter:
            self.assertTrue(adapter.wait_once(0))
        self.assertEqual(self.calls, ["reconcile"])

    def test_restart_between_events_uses_a_new_adapter_without_event_state(self):
        first_kqueue, first_kevent = self.adapter([[object()]])
        with first_kqueue, first_kevent, KqueueSignalAdapter(self.root, lambda: self.calls.append("first")) as adapter:
            self.assertTrue(adapter.wait_once(0))
        second_kqueue, second_kevent = self.adapter([[object()]])
        with second_kqueue, second_kevent, KqueueSignalAdapter(self.root, lambda: self.calls.append("second")) as adapter:
            self.assertTrue(adapter.wait_once(0))
        self.assertEqual(self.calls, ["first", "second"])

    def test_deleted_directory_or_kqueue_failure_is_only_a_reconcile_hint(self):
        kqueue, kevent = self.adapter([OSError("revoked")])
        with kqueue, kevent, KqueueSignalAdapter(self.root, lambda: self.calls.append("reconcile")) as adapter:
            self.assertTrue(adapter.wait_once(0))
        self.assertEqual(self.calls, ["reconcile"])

    def test_permission_denied_does_not_create_an_adapter(self):
        with patch("epistates.signal_events.os.open", side_effect=PermissionError):
            with self.assertRaises(SignalEventError):
                KqueueSignalAdapter(self.root, lambda: self.calls.append("unexpected"))
        self.assertEqual(self.calls, [])

    def test_closed_adapter_and_invalid_timeout_fail_closed(self):
        kqueue, kevent = self.adapter([[]])
        with kqueue, kevent, KqueueSignalAdapter(self.root, lambda: self.calls.append("unexpected")) as adapter:
            for value in (-1, 61, float("nan"), True):
                with self.assertRaises(ValueError):
                    adapter.wait_once(value)
            adapter.close()
            with self.assertRaises(SignalEventError):
                adapter.wait_once(0)
