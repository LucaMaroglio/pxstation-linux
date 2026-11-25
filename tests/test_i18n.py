"""Interface language: system detection, fallback to English, complete Italian catalog.

    python3 -m unittest discover -s tests -p test_i18n.py -v
"""

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from linux_spice_client.core import i18n  # noqa: E402


def source_texts() -> set[str]:
    """Every literal passed to _() in the package."""
    texts = set()
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "linux_spice_client")):
        for name in files:
            if not name.endswith(".py"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    texts.add(node.args[0].value)
    return texts


class LanguageTests(unittest.TestCase):
    def test_supported_languages(self):
        self.assertEqual(i18n.supported_languages()[0], "en")
        self.assertIn("it", i18n.supported_languages())

    def test_system_language(self):
        self.assertEqual(i18n.system_language({"LANG": "it_IT.UTF-8"}), "it")
        self.assertEqual(i18n.system_language({"LANG": "en_US.UTF-8", "LC_MESSAGES": "it_IT.UTF-8"}), "it")
        self.assertEqual(i18n.system_language({"LANG": "fr_FR.UTF-8", "LANGUAGE": "fr:it"}), "it")

    def test_unsupported_system_language_falls_back_to_english(self):
        self.assertEqual(i18n.system_language({"LANG": "fr_FR.UTF-8"}), "en")
        self.assertEqual(i18n.system_language({"LANG": "C"}), "en")
        self.assertEqual(i18n.system_language({}), "en")

    def test_language_is_ignored_with_the_c_locale(self):
        self.assertEqual(i18n.system_language({"LANG": "C", "LANGUAGE": "it"}), "en")

    def test_load(self):
        i18n.load("it")
        try:
            self.assertEqual(i18n._("Connect"), "Connetti")
            self.assertEqual(i18n._("not in the catalog"), "not in the catalog")
        finally:
            i18n.load("en")
        self.assertEqual(i18n._("Connect"), "Connect")


class CatalogTests(unittest.TestCase):
    def test_italian_catalog_is_complete(self):
        with open(os.path.join(ROOT, "data", "locale", "it.json"), encoding="utf-8") as handle:
            strings = json.load(handle)["strings"]
        self.assertEqual(sorted(source_texts() - set(strings)), [])

    def test_placeholders_match(self):
        import string
        with open(os.path.join(ROOT, "data", "locale", "it.json"), encoding="utf-8") as handle:
            strings = json.load(handle)["strings"]
        fields = lambda text: sorted(f for _l, f, _s, _c in string.Formatter().parse(text) if f)  # noqa: E731
        for english, italian in strings.items():
            self.assertEqual(fields(english), fields(italian), english)


if __name__ == "__main__":
    unittest.main()
