# Alibaba Cloud IaC

This Terraform module defines four isolated ECS workloads: the front, back, and
integration agents plus a separate control plane. Each workload has its own VPC,
VSwitch, NAT Gateway, EIP, SNAT rule, and security group. The Singapore region
`ap-southeast-1` is only a default; region, zone, exact ECS image ID and image
digest are explicit inputs. Instance types, disk sizes, CIDRs, and egress profiles
are also inputs because availability and account limits have not been checked.

## Network policy

The module adds no ingress rules and assigns no public address to an ECS instance.
Internet egress leaves through that workload's NAT Gateway. Security groups allow
only the configured model proxy, private Git, TCP DNS, HTTPS time source, Cloud
Assistant endpoints, and the profile-specific UDP destinations. The security
group's default egress policy is `drop`. `direct` allows UDP only to configured peer CIDRs
and relay CIDRs/ports; `relay-only` allows only relay CIDRs/ports; `udp-blocked`
adds no UDP rule. Each VM can use Alibaba Cloud Assistant as its outbound-only
management path; there is no SSH key or inbound SSH rule in this module.

Private model-proxy and Git CIDRs must already be routable from the workload VPCs
through an approved private connection. This module intentionally does not create
cross-VPC routes or authorize agent-to-agent traffic. Cloud Assistant, resolver,
time-source, peer, relay, and service CIDRs must be narrow values provided by the
operator. The resulting policy describes configured reachability only; it does
not prove actual egress or P2P selected paths.

## Image and retention

The image is pinned by exact `image_id`, with its build digest recorded as a tag.
The source does not build an image, inject credentials, or set a login password.
Cloud credentials are read by the Alibaba provider from its normal runtime
credential chain; do not put credentials in `.tfvars`, the module, or state shared
with agents. Workload secrets must be injected at runtime by the external
provisioning controller or secret manager.

System disks use `system_disk_delete_with_instance = false`. Baseline snapshots
and all resource lifecycles have `prevent_destroy`; there is no cleanup or delete
workflow here. Review state, provider prices, quotas, image availability, endpoint
routing, and the generated plan before any operator-run apply. This task does not
run Terraform or call Alibaba Cloud.

## Inputs

Use a private, access-controlled variable source for environment-specific IDs and
CIDRs. Do not commit a `.tfvars` file. Each workload object requires `instance_type`,
`system_disk_size`, `vpc_cidr`, `vswitch_cidr`, `network_profile`, `peer_udp_cidrs`,
`relay_udp_cidrs`, and `relay_udp_ports`. All service CIDR inputs are explicit;
there are no broad default egress destinations.
