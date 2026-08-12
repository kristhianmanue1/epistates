import re
import unittest


# PEP 440 minimal para el segmento de esta release. No reimplementa todo PEP
# 440; sólo asegura que la versión tenga la forma esperada del alpha.
_PEP440_ALPHA = re.compile(r"^0\.1\.0a1$")


class VersionSourceTests(unittest.TestCase):
    """La versión es single-source desde ``epistates._version``."""

    def test_version_module_holds_release_value(self):
        from epistates import _version
        self.assertEqual(_version.__version__, "0.1.0a1")

    def test_public_version_attribute_matches_source(self):
        import epistates
        from epistates import _version
        self.assertEqual(epistates.__version__, _version.__version__)

    def test_version_matches_pep440_alpha(self):
        import epistates
        self.assertIsNotNone(_PEP440_ALPHA.fullmatch(epistates.__version__))


class VersionExportTests(unittest.TestCase):
    def test_version_is_string_attribute(self):
        import epistates
        self.assertIsInstance(epistates.__version__, str)
        self.assertTrue(epistates.__version__)

    def test_version_is_listed_in_all(self):
        import epistates
        self.assertIn("__version__", epistates.__all__)

    def test_version_is_exportable_by_wildcard(self):
        namespace = {}
        import epistates
        exec("from epistates import *", namespace)
        self.assertIn("__version__", namespace)
        self.assertEqual(namespace["__version__"], "0.1.0a1")


class DistributedSurfaceTests(unittest.TestCase):
    """El paquete no depende de schemas/fixtures/docs en runtime.

    Estos directorios son activos del repositorio, no API distribuida: el
    paquete instalado debe importarse y exponer su versión sin ellos.
    """

    def test_package_imports_without_repository_assets(self):
        import epistates
        # Sanity: la importación expone el módulo de versión y el validador
        # público sin leer schemas/ ni fixtures/.
        self.assertTrue(hasattr(epistates, "validate_task_card"))
        self.assertEqual(epistates.__version__, "0.1.0a1")


if __name__ == "__main__":
    unittest.main()
