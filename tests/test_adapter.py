import json
import copy
import unittest
from pathlib import Path

from epistates.adapter import validate_adapter_capabilities
from epistates.contracts import ValidationError


FIXTURES = Path(__file__).parent.parent / "fixtures"


class AdapterCapabilitiesTests(unittest.TestCase):
    def load(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_accepts_opencode_tmux(self):
        validate_adapter_capabilities(self.load("adapter-capabilities-opencode-tmux.json"))

    def test_adapter_id_opencode_tmux_is_valid_neutrality(self):
        # La neutralidad la dan los catalogos cerrados, no el nombre del host.
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        self.assertEqual(adapter["adapter_id"], "opencode-tmux")
        validate_adapter_capabilities(adapter)

    def test_rejects_unknown_capability(self):
        with self.assertRaisesRegex(ValidationError, "no soportado"):
            validate_adapter_capabilities(self.load("adapter-capabilities-bad-capability.json"))

    def test_rejects_unsupported_platform(self):
        with self.assertRaisesRegex(ValidationError, "no soportado"):
            validate_adapter_capabilities(self.load("adapter-capabilities-bad-platform.json"))

    def test_rejects_empty_platforms(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["platforms"] = []
        with self.assertRaisesRegex(ValidationError, "no vacia"):
            validate_adapter_capabilities(adapter)

    def test_rejects_duplicate_capability(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["capabilities"] = ["observe_session", "observe_session"]
        with self.assertRaisesRegex(ValidationError, "duplicado"):
            validate_adapter_capabilities(adapter)

    def test_rejects_duplicate_platform(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["platforms"] = ["darwin", "darwin"]
        with self.assertRaisesRegex(ValidationError, "duplicado"):
            validate_adapter_capabilities(adapter)

    def test_rejects_bad_version(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["version"] = "v2"
        with self.assertRaisesRegex(ValidationError, "version"):
            validate_adapter_capabilities(adapter)

    def test_rejects_unknown_field(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["send_keys"] = True
        with self.assertRaisesRegex(ValidationError, "no permitidos"):
            validate_adapter_capabilities(adapter)

    def test_rejects_missing_field(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        del adapter["capabilities"]
        with self.assertRaisesRegex(ValidationError, "ausentes"):
            validate_adapter_capabilities(adapter)

    def test_rejects_bad_adapter_id_and_surrogate_without_traceback(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["adapter_id"] = "UPPER"
        with self.assertRaisesRegex(ValidationError, "adapter_id"):
            validate_adapter_capabilities(adapter)
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["adapter_id"] = "op\u2013code"
        with self.assertRaises(ValidationError):
            validate_adapter_capabilities(adapter)
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["adapter_id"] = "\ud800"
        with self.assertRaises(ValidationError):
            validate_adapter_capabilities(adapter)

    def test_rejects_hostile_types_without_traceback(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["platforms"] = "darwin"
        with self.assertRaises(ValidationError):
            validate_adapter_capabilities(adapter)
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        adapter["capabilities"] = 42
        with self.assertRaises(ValidationError):
            validate_adapter_capabilities(adapter)

    def test_rejects_non_mapping(self):
        with self.assertRaises(ValidationError):
            validate_adapter_capabilities(["not", "a", "mapping"])

    def test_does_not_mutate_input(self):
        adapter = self.load("adapter-capabilities-opencode-tmux.json")
        snapshot = copy.deepcopy(adapter)
        validate_adapter_capabilities(adapter)
        self.assertEqual(adapter, snapshot)
