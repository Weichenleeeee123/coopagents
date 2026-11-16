# DSH Sandbox Provider Inventory Contract

This contract is provider-neutral. A provider adapter may translate its read-only
inventory/export into the shape below; validation does not provision, mutate,
deallocate, or delete resources. An empty error list proves only that the supplied
inventory is structurally consistent. It is not proof of packet behavior, independent
NAT observation, cloud acceptance, or a real DSH run.

The operator selected Alibaba Cloud for the later provider stage, using Singapore
region `ap-southeast-1` as the default. The region must remain an overridable runtime
input. This contract does not inspect an account, validate quota, call Alibaba Cloud,
or authorize infrastructure creation. The Alibaba Cloud Terraform source is in
`iac/alicloud/`; it defines isolated workloads but requires an already-routable
approved private path to the shared proxy and Git endpoints. It does not create
cross-VPC routing or establish actual P2P reachability.

## Inventory shape

Input is a mapping with a non-empty `run_id` and exactly three `agents` records. The
three records represent the front-end, back-end, and integration DSH members. Values
are identifiers from a synthetic fixture or provider inventory export; never include
credentials, initialization output, prompt content, or private addresses in diagnostics.

Each record contains:

| Field | Contract |
| --- | --- |
| `agent_id` | Required, unique non-empty member VM alias/identity. |
| `egress_network_id` | Required and unique per agent; identifies its independent NAT/egress network. |
| `public_ip` | Required valid and unique egress IP observation for that NAT path, not a VM inbound address. |
| `subnet_id` | Required and unique per agent. |
| `inbound_ports` | Must be an empty array. SSH (22), RDP (3389), and every other unsolicited inbound port are prohibited. |
| `public_control_endpoint` | Must be the boolean `false`; control access must remain private. |
| `network_profile` | One of `direct`, `relay-only`, or `udp-blocked`. |
| `network_policy` | Boolean `peer_udp` and `relay_udp` values matching the selected profile below. |
| `lifecycle` | Run-bound instance state and a bounded expiry, plus preserving deallocation metadata. |
| `snapshot` | Source image, snapshot identity, creation time, and pinned image digest. |

All timestamps use timezone-aware ISO 8601 values. The lifecycle expiry must follow
creation. The lifecycle run ID and deallocation action run ID must both exactly match
the top-level current `run_id`.

The deallocation record is a guard description, not an executable action. It must use
`mode: stop` or `mode: deallocate`, set `preview_required: true`, and preserve disks,
snapshots, and evidence. Destruction is outside this contract. In particular, the
validator does not provide a delete path or recommend removing retained artifacts.

## Network profiles

| Profile | `peer_udp` | `relay_udp` | Meaning |
| --- | --- | --- | --- |
| `direct` | `true` | `true` | Permit stateful outbound peer UDP and the configured relay/discovery traffic; unsolicited inbound remains blocked. |
| `relay-only` | `false` | `true` | Permit the configured Coopagents relay UDP endpoint; block peer-direct UDP. |
| `udp-blocked` | `false` | `false` | Block UDP as a negative control. |

These booleans describe intended policy only. Runtime-selected direct, relay, or
unreachable paths require separate observed evidence. All three profiles must also
limit non-UDP egress to the configured model proxy, that member's local MCP gateway,
private Git, DNS, and NTP. The provider-specific adapter must preserve and verify those
destinations when it is added; an inventory passing this structural validator does
not establish enforcement.

## Validation

The standard-library validator is
`experiments/agent-integration/dsh_sandbox/provider_contract.py`. It returns a list of
field-level errors and never includes inventory values in diagnostics. Tests use
synthetic inventories only:

```powershell
python -m unittest discover -s tests -p 'test_dsh_sandbox_provider_contract.py' -v
```

No cloud CLI/API, account credentials, resource creation, packet probe, or real DSH
session is involved in this check.
