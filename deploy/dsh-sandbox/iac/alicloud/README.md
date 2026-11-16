# Alibaba Cloud IaC

This Terraform module defines four isolated ECS workloads: the front, back, and
integration agents plus a separate control plane. Each workload has its own VPC,
VSwitch, NAT Gateway, EIP, SNAT rule, and security group. The Singapore region
`ap-southeast-1` is only a default; region, zone, exact ECS image ID and image
digest are explicit inputs. Instance types, disk sizes, CIDRs, and egress profiles
are also inputs because availability and account limits have not been checked.

## Network policy

The agent workloads have no ingress rules. Only the control plane has private
ingress from the three agent VSwitch CIDRs, limited to the model-proxy TLS port and
private Git SSH port. No ECS instance receives a public address. Internet egress
leaves through that workload's NAT Gateway. Security groups allow
only the configured model proxy, private Git, TCP DNS, HTTPS time source, Cloud
Assistant endpoints, and the profile-specific UDP destinations. The security
group has an explicit priority-100 drop rule for all destinations/protocols;
specific allow rules use priority 1. This overrides the basic group's lower
precedence default outbound allow behavior. `direct` allows UDP only to configured peer CIDRs
and relay CIDRs/ports; `relay-only` allows only relay CIDRs/ports; `udp-blocked`
adds no UDP rule. Each VM can use Alibaba Cloud Assistant as its outbound-only
management path; there is no SSH key or inbound SSH rule in this module.

Private model-proxy and Git CIDRs must already be routable from the workload VPCs
through an approved private connection. This module intentionally does not create
cross-VPC routes or authorize agent-to-agent traffic. Cloud Assistant, resolver,
time-source, peer, relay, and service CIDRs must be narrow values provided by the
operator. The resulting policy describes configured reachability only; it does
not prove actual egress or P2P selected paths. The operator must set `model_proxy_cidrs`
and `private_git_cidrs` to the reachable private endpoint CIDRs and establish routing
from each agent VPC to the control VPC before provisioning.

## Image and retention

The image is pinned by exact `image_id`, with its build digest recorded as a tag.
The source does not build an image, inject credentials, or set a login password.
Cloud credentials are read by the Alibaba provider from its normal runtime
credential chain; do not put credentials in `.tfvars`, the module, or state shared
with agents. Workload secrets must be injected at runtime by the external
provisioning controller or secret manager.

The pinned provider's `alicloud_instance` does not support independently retaining
its system disk on instance deletion. Instances and baseline snapshots have
`prevent_destroy`, so this module refuses Terraform destruction while that guard
remains in configuration; it does not guarantee disk retention if a VM is deleted
outside Terraform or the guard is removed. Stop/deallocate the VM rather than
delete it. No cleanup/delete workflow is provided. Review state, provider prices,
quotas, image availability, endpoint
routing, and the generated plan before any operator-run apply. This task does not
run Terraform or call Alibaba Cloud.

`workload_inventory` emits only the three agent records in the provider validator's
shape. It includes provider-reported instance/snapshot timestamps and requires an
operator-supplied `run_expires_at`; the separate control-plane record is available
as `control_plane_inventory`. Public EIP values and provider inventory do not prove
runtime reachability or a selected P2P path.

## Inputs

Use a private, access-controlled variable source for environment-specific IDs and
CIDRs. Do not commit a `.tfvars` file. Each workload object requires `instance_type`,
`system_disk_size`, `vpc_cidr`, `vswitch_cidr`, `network_profile`, `peer_udp_cidrs`,
`relay_udp_cidrs`, and `relay_udp_ports`. All service CIDR inputs are explicit;
there are no broad default egress destinations.

## Provider compatibility checks

The pinned v1.243.0 source schema has no security-group `egress_rule` attribute and
no instance `system_disk_delete_with_instance` attribute. Its NAT `snat_table_ids`
is a comma-separated string, so the single NAT SNAT table is extracted with
`split(",", ...)[0]`; `system_disk_id` is a computed instance output. The offline
regression test `tests/test_dsh_sandbox_alicloud.py` checks these known schema
constraints and generated UDP protocol fields. It is not a full Terraform schema
validation. Terraform/provider initialization and real policy observation remain
operator steps.
