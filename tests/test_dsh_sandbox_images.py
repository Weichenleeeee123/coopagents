import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "deploy" / "dsh-sandbox" / "images"


class SandboxImageManifestTests(unittest.TestCase):
    def read_manifest(self, name):
        return json.loads((IMAGES / name / "image.json").read_text(encoding="utf-8"))

    def test_images_require_digest_pinned_overridable_inputs_and_versioned_packages(self):
        for name in ("agent", "control-plane"):
            with self.subTest(image=name):
                manifest = self.read_manifest(name)
                self.assertEqual(manifest["schema_version"], 1)
                base = manifest["base_image"]
                self.assertTrue(base["required"])
                self.assertTrue(base["overridable"])
                self.assertRegex(base["value"], r"^\$\{[A-Z0-9_]+\}$")
                self.assertEqual(base["digest"], "${BASE_IMAGE_SHA256}")
                self.assertEqual(manifest["build_digest"], "${BUILD_SHA256}")
                self.assertEqual(base["digest_pattern"], "^sha256:[0-9a-f]{64}$")
                self.assertTrue(manifest["packages"])
                for package in manifest["packages"]:
                    self.assertTrue(package["version"])
                    if package["version"] == "REQUIRED_INPUT":
                        self.assertIn("verified", package)
                        self.assertFalse(package["verified"])

    def test_agent_image_has_split_accounts_loopback_gateway_and_isolated_home(self):
        manifest = self.read_manifest("agent")
        self.assertEqual(manifest["accounts"]["dsh"], "dsh")
        self.assertEqual(manifest["accounts"]["gateway"], "dsh-gateway")
        self.assertNotEqual(manifest["accounts"]["dsh"], manifest["accounts"]["gateway"])
        self.assertEqual(manifest["dsh_home"], "/var/lib/dsh/profiles/${RUN_ID}/${AGENT_ALIAS}")
        service = (IMAGES / "agent" / "dsh-gateway.service").read_text(encoding="utf-8")
        self.assertIn("User=dsh-gateway", service)
        self.assertEqual(manifest["gateway_bind"], "127.0.0.1")
        self.assertIn("IPAddressAllow=localhost", service)
        self.assertIn("NoNewPrivileges=true", service)

    def test_control_plane_contains_only_separate_non_dsh_services(self):
        manifest = self.read_manifest("control-plane")
        self.assertEqual(set(manifest["services"]), {"coordinator", "model_proxy", "private_git", "evidence_collector"})
        self.assertFalse(manifest["accounts"].get("dsh"))
        self.assertEqual(len(set(manifest["accounts"].values())), 4)

    def test_bootstrap_is_idempotent_non_destructive_and_credentials_are_runtime_only(self):
        for name in ("agent", "control-plane"):
            with self.subTest(image=name):
                bootstrap = (IMAGES / name / "bootstrap.sh").read_text(encoding="utf-8")
                self.assertIn("set -eu", bootstrap)
                self.assertNotRegex(bootstrap, r"(?im)^\s*(?:rm|userdel|deluser|mkfs|wipefs)\b")
                self.assertNotRegex(bootstrap, r"(?i)(?:password|secret|api[_-]?key)\s*[:=]\s*['\"]?[^\s]{8,}")
                self.assertNotRegex(bootstrap, r"(?i)(?:ssh-rsa|BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY)")
                self.assertNotIn("169.254.169.254", bootstrap)
                self.assertNotIn("alicloud", bootstrap.lower())

    def test_agent_profile_setup_never_embeds_credentials_and_preserves_existing_config(self):
        bootstrap = (IMAGES / "agent" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("cordis.patch.yml", bootstrap)
        self.assertRegex(bootstrap, r"(?i)(?:test\s+-e|\[\s+-e).*cordis\.patch\.yml")
        self.assertIn("http://127.0.0.1:8769/mcp", bootstrap)
        self.assertNotRegex(bootstrap, r"(?i)authorization|bearer\s|api[_-]?key|member[_-]?token")

    def test_manifests_and_services_define_no_ingress_or_public_management_path(self):
        for path in IMAGES.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?im)^\s*(?:ports|ingress|public_ip|ssh_authorized_keys)\s*:")
            self.assertNotRegex(text, r"(?i)(?:0\.0\.0\.0|::):(?:22|3389)\b")
            self.assertNotRegex(text, r"(?im)^\s*ListenAddress\s+0\.0\.0\.0\b")


if __name__ == "__main__":
    unittest.main()
