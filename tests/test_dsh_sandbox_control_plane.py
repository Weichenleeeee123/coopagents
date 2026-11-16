import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent-integration"))

from dsh_sandbox.control_plane import (
    AppendOnlyUsageLedger,
    ControlPlaneConfig,
    load_client_credentials,
    validate_bind_address,
    validate_git_endpoint,
)


class ConfigurationTests(unittest.TestCase):
    def test_bind_must_be_explicit_private_unicast(self):
        for address in ("0.0.0.0", "203.0.113.20", "::"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                validate_bind_address(address)
        self.assertEqual(validate_bind_address("10.20.0.5"), "10.20.0.5")
        self.assertEqual(validate_bind_address("fd00::5"), "fd00::5")

    def test_git_service_is_an_explicit_private_ssh_dependency(self):
        self.assertEqual(validate_git_endpoint("ssh://git@10.20.0.8/repos/synthetic.git"),
                         "ssh://git@10.20.0.8/repos/synthetic.git")
        self.assertEqual(validate_git_endpoint("ssh://git@git.internal/repos/synthetic.git"),
                         "ssh://git@git.internal/repos/synthetic.git")
        for endpoint in ("https://github.com/acme/repo.git", "ssh://git@github.com/acme/repo.git",
                         "ssh://git@203.0.113.8/repo.git", "ssh://user:pass@git.internal/repo.git"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_git_endpoint(endpoint)

    def test_runtime_credentials_are_validated_without_values_in_diagnostics(self):
        good = json.dumps({"vm-token-secret": "run_123"})
        with patch("builtins.open", mock_open(read_data=good)):
            self.assertEqual(load_client_credentials("runtime-credential-handle"),
                             {"vm-token-secret": "run_123"})
        with patch("builtins.open", mock_open(read_data='{"token-secret":"bad run id"}')):
            with self.assertRaisesRegex(ValueError, "credential") as error:
                load_client_credentials("runtime-credential-handle")
        self.assertNotIn("token-secret", str(error.exception))

    def test_config_requires_tls_material_and_valid_budget(self):
        base = dict(bind_address="10.20.0.5", port=9443,
                    cert_file="runtime-cert", key_file="runtime-key",
                    git_ssh_url="ssh://git@git.internal/repo.git",
                    endpoint="https://provider.example/v1/chat/completions",
                    model="fixed", provider_key="runtime-key-value",
                    client_tokens={"vm-token": "run_1"},
                    max_requests_per_run=5, max_tokens_per_run=500,
                    max_cost_per_run=2.0, input_cost_per_million=1.0,
                    output_cost_per_million=2.0)
        config = ControlPlaneConfig(**base)
        self.assertEqual(config.bind_address, "10.20.0.5")
        for overrides in ({"port": 0}, {"max_requests_per_run": True},
                          {"max_cost_per_run": float("nan")}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                ControlPlaneConfig(**(base | overrides))


class UsageLedgerTests(unittest.TestCase):
    def test_append_records_only_run_id_and_usage_and_uses_exclusive_create(self):
        ledger_path = ".local/dsh-sandbox-runs/run-uuid/usage.jsonl"
        with patch("pathlib.Path.mkdir"), patch("os.open", return_value=17) as open_file, \
                patch("os.write") as write_file:
            ledger = AppendOnlyUsageLedger(ledger_path)
            ledger("run_123", {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3})
        self.assertEqual(str(open_file.call_args.args[0]).replace("\\", "/"), ledger_path)
        self.assertEqual(open_file.call_args.args[1] & os.O_EXCL, os.O_EXCL)
        record = json.loads(write_file.call_args.args[1])
        self.assertEqual(record["run_id"], "run_123")
        self.assertEqual(record["usage"]["total_tokens"], 3)
        self.assertNotIn("messages", record)

    def test_unknown_usage_stays_null_and_untrusted_run_ids_are_rejected(self):
        with patch("pathlib.Path.mkdir"), patch("os.open", return_value=17), \
                patch("os.write") as write_file:
            ledger = AppendOnlyUsageLedger(".local/dsh-sandbox-runs/run-uuid/usage.jsonl")
            ledger("run_123", None)
        self.assertIsNone(json.loads(write_file.call_args.args[1])["usage"])
        with self.assertRaises(ValueError):
            ledger("prompt-secret\nforged", None)


if __name__ == "__main__":
    unittest.main()
