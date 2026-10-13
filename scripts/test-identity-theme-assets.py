"""Exercise both theme build paths against old resource-cache URLs."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ThemeAssetVersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.script = self.root / "scripts/build-identity-theme.py"
        self.script.parent.mkdir()
        shutil.copyfile(ROOT / "scripts/build-identity-theme.py", self.script)
        self.theme = self.root / "identity/themes/actvero/login"
        (self.theme / "resources/css").mkdir(parents=True)
        (self.theme / "resources/js").mkdir()
        self.css = self.theme / "resources/css/generated.css"
        self.css.write_text(".dark .logo { display: none }")
        self.js = self.theme / "resources/js/actvero.js"
        self.js.write_text("const theme = 'dark'")
        self.properties = self.theme / "theme.properties"
        self.properties.write_text("parent=keycloak\nactveroThemeVersion=old\n")

    def build(self, mode="--version"):
        subprocess.run([sys.executable, str(self.script), mode], check=True, capture_output=True)
        content = self.properties.read_text()
        self.assertIn("parent=keycloak\n", content)
        versions = re.findall(r"^actveroThemeVersion=([0-9a-f]{16})$", content, re.M)
        self.assertEqual(len(versions), 1)
        return versions[0]

    def test_unchanged_assets_reuse_url_but_css_and_js_changes_invalidate_it(self):
        initial = self.build()
        self.assertEqual(self.build(), initial)
        self.css.write_text(".dark .logo { display: inline-flex }")
        changed_css = self.build()
        self.assertNotEqual(changed_css, initial)
        self.js.write_text("const theme = 'light'")
        self.assertNotEqual(self.build(), changed_css)

    def test_production_copy_and_standalone_build_use_same_version(self):
        assets = self.root / "frontend/dist/assets"
        assets.mkdir(parents=True)
        css = ".dark .logo { display: inline-flex }"
        (assets / "index-test.css").write_text(css)
        production = self.build("--css")
        self.assertEqual(self.css.read_text(), css)
        self.assertEqual(self.build(), production)


if __name__ == "__main__":
    unittest.main()
