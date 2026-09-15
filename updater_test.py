"""Mises à jour : réseau simulé, aucune installation exécutée."""
import hashlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app import updater as desktop
from server import updater as console


class UpdaterTests(unittest.TestCase):
    def asset(self, content=b"complete"):
        return {"name": "EMAB-Gestionnaire-Setup-2.0.0.exe", "size": len(content),
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "browser_download_url": "https://example.test/setup.exe"}

    def test_partial_and_wrong_content_are_never_activated(self):
        for module in (desktop, console):
            for content in (b"short", b"bad-data"):
                with self.subTest(module=module.__name__, content=content), TemporaryDirectory() as tmp:
                    asset = self.asset()
                    with patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(content)):
                        with self.assertRaises(ValueError):
                            module._download_asset(asset, Path(tmp))
                    self.assertFalse((Path(tmp) / module.UPDATES_DIR / asset["name"]).exists())
                    self.assertEqual(list((Path(tmp) / module.UPDATES_DIR).iterdir()), [])

    def test_valid_download_is_reused_without_network(self):
        for module in (desktop, console):
            with self.subTest(module=module.__name__), TemporaryDirectory() as tmp:
                with patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(b"complete")) as request:
                    target = module._download_asset(self.asset(), Path(tmp))
                    self.assertEqual(module._download_asset(self.asset(), Path(tmp)), target)
                    self.assertEqual(target.read_bytes(), b"complete")
                    request.assert_called_once()

    def test_partial_download_never_creates_update_flag(self):
        for module, fetch in ((desktop, "_fetch_latest_desktop_release"), (console, "_fetch_latest_release")):
            with self.subTest(module=module.__name__), TemporaryDirectory() as tmp:
                asset = self.asset()
                asset["name"] = module.ASSET_HINT + "-2.0.0.exe"
                with patch.object(module, fetch, return_value={"tag_name": "v2.0.0", "assets": [asset]}), patch.object(
                        module.urllib.request, "urlopen", return_value=io.BytesIO(b"short")):
                    self.assertIsNone(module.check_and_prepare_update("1.0.0", Path(tmp)))
                self.assertFalse((Path(tmp) / module.FLAG_NAME).exists())

    def test_download_name_cannot_escape_updates_folder(self):
        for module in (desktop, console):
            with self.subTest(module=module.__name__), TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    module._download_asset(dict(self.asset(), name="../setup.exe"), Path(tmp))


if __name__ == "__main__":
    unittest.main()
