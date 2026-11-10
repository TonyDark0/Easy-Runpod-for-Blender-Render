import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("setup_test_package")
package.__path__ = [str(ROOT / "addon/runpod_render")]
sys.modules[package.__name__] = package
from setup_test_package import setup, credentials


class SetupTests(unittest.TestCase):
    def test_gpu_profile_excludes_mig_and_keeps_provider_rate(self):
        catalog = {"gpus": [
            dict(id="NVIDIA RTX 3090", name="RTX 3090", pool="AMPERE_24", price={"serverless": 0.75}),
            dict(id="NVIDIA PRO 6000 MIG 24GB", name="MIG", pool="AMPERE_24", price={"serverless": 0.75})]}
        gpu, rate, label = setup.gpu_selection(catalog, "AMPERE_24")
        self.assertEqual(gpu["excludedTypes"], ["NVIDIA PRO 6000 MIG 24GB"])
        self.assertEqual(rate, .75)
        self.assertEqual(label, "RTX 3090")

    def test_setup_uses_one_flex_worker_and_never_passes_runpod_key(self):
        data = dict(client_id="client", client_secret="desktop", refresh_token="refresh", api_key="never-send")
        payload = setup.endpoint_payload("test", {"pools": ["ADA_24"]}, data, 240, 50)
        self.assertEqual(payload["workers"], dict(min=0, max=1, idleTimeout=5))
        self.assertEqual(payload["timeout"], 14400000)
        self.assertNotIn("api_key", payload["env"])
        self.assertNotIn("never-send", str(payload))

    def test_updates_refuse_running_jobs(self):
        with patch.object(setup, "api", return_value={"jobs": {"inProgress": 1}}) as api:
            with self.assertRaisesRegex(ValueError, "finish"):
                setup.provision("key", {}, "existing")
            self.assertEqual(api.call_count, 1)

    def test_failed_create_is_not_retried(self):
        with patch.object(setup, "api", side_effect=TimeoutError) as api:
            with self.assertRaises(TimeoutError):
                setup.provision("key", {})
            self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
