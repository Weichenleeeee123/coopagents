from pathlib import Path
import re
import unittest


IAC = Path(__file__).resolve().parents[1] / 'deploy' / 'dsh-sandbox' / 'iac' / 'alicloud'
MAIN = (IAC / 'main.tf').read_text(encoding='utf-8')
OUTPUTS = (IAC / 'outputs.tf').read_text(encoding='utf-8')
VARIABLES = (IAC / 'variables.tf').read_text(encoding='utf-8')


class DshSandboxAlibabaTerraformTests(unittest.TestCase):
    def test_security_group_uses_supported_explicit_deny_and_narrow_allow_rules(self):
        self.assertNotRegex(MAIN, r'(?m)^\s*egress_rule\s*=')
        self.assertRegex(MAIN, r'resource\s+"alicloud_security_group_rule"\s+"deny_unlisted_egress"')
        self.assertRegex(MAIN, r'(?s)resource\s+"alicloud_security_group_rule"\s+"deny_unlisted_egress"\s*\{.*?policy\s*=\s*"drop".*?priority\s*=\s*100')
        self.assertRegex(MAIN, r'(?s)resource\s+"alicloud_security_group_rule"\s+"allow_egress"\s*\{.*?policy\s*=\s*"accept".*?priority\s*=\s*1')

    def test_udp_profile_rules_set_udp_protocol(self):
        udp_block = re.search(r'(?s)profile_udp_rules\s*=\s*flatten\(\[(.*?)\]\)\s*\n\s*egress_rules', MAIN)
        self.assertIsNotNone(udp_block)
        self.assertEqual(len(re.findall(r'protocol\s*=\s*"udp"', udp_block.group(1))), 2)

    def test_only_control_plane_has_narrow_agent_subnet_ingress(self):
        self.assertRegex(MAIN, r'(?s)resource\s+"alicloud_security_group_rule"\s+"control_plane_private_ingress"\s*\{.*?security_group_id\s*=\s*alicloud_security_group\.this\["control"\]\.id')
        self.assertIn('if name != "control"', MAIN)
        self.assertIn('workload.vswitch_cidr', MAIN)
        self.assertIn('default     = 22', VARIABLES)
        self.assertIn('type              = "ingress"', MAIN)

    def test_provider_string_attributes_are_not_indexed_or_unsupported(self):
        self.assertNotIn('snat_table_ids[0]', MAIN)
        self.assertIn('snat_table_id  = split(",", alicloud_nat_gateway.this[each.key].snat_table_ids)[0]', MAIN)
        self.assertNotIn('system_disk_delete_with_instance', MAIN)
        self.assertIn('system_disk_id', MAIN)
        self.assertIn('alicloud_nat_gateway.this[name].id', OUTPUTS)

    def test_provider_inventory_output_matches_three_agent_validator_contract(self):
        self.assertIn('variable "run_expires_at"', VARIABLES)
        self.assertIn('agents = [', OUTPUTS)
        self.assertIn('["front", "back", "integration"]', OUTPUTS)
        for field in ('agent_id', 'egress_network_id', 'public_ip', 'subnet_id',
                      'network_policy', 'created_at', 'expires_at', 'deallocation',
                      'snapshot_id', 'source_image_id', 'image_digest'):
            self.assertIn(field, OUTPUTS)
        self.assertIn('output "control_plane_inventory"', OUTPUTS)


if __name__ == '__main__':
    unittest.main()
