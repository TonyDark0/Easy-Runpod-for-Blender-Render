import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("credentials", ROOT / "addon/runpod_render/credentials.py")
credentials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credentials)


class CredentialsTests(unittest.TestCase):
    def test_roundtrip_and_windows_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            data = {"refresh_token": "synthetic-test-token", "folder": "synthetic-folder"}
            credentials.write_credentials(path, data)
            self.assertEqual(credentials.read_credentials(path), data)
            if os.name == "nt":
                self.assertNotIn("synthetic-test-token", path.read_text())

    def test_existing_credentials_remain_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            data = {"refresh_token": "legacy-synthetic-token"}
            path.write_text(json.dumps(data))
            self.assertEqual(credentials.read_credentials(path), data)


if __name__ == "__main__":
    unittest.main()
