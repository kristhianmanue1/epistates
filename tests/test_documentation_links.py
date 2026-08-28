import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_documentation_links.py"
SPEC = importlib.util.spec_from_file_location("check_documentation_links", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class DocumentationLinksTests(unittest.TestCase):
    def test_existing_relative_link_passes_and_external_links_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.md"
            target.write_text("# target\n", encoding="utf-8")
            source = root / "source.md"
            source.write_text(
                "[local](target.md) [web](https://example.test) [anchor](#here)\n",
                encoding="utf-8",
            )
            self.assertEqual(module.check_paths([source]), [])

    def test_missing_relative_link_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.md"
            source.write_text("[missing](missing.md)\n", encoding="utf-8")
            failures = module.check_paths([source])
            self.assertEqual(len(failures), 1)
            self.assertIn("enlace local inexistente", failures[0])

    def test_absolute_link_outside_project_fails_without_probing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.md"
            source.write_text("[outside](/etc/passwd)\n", encoding="utf-8")
            failures = module.check_paths([source])
            self.assertEqual(len(failures), 1)
            self.assertIn("enlace local fuera del proyecto", failures[0])
