locals {
  workloads = var.workloads
  agent_source_cidrs = [
    for name, workload in local.workloads : workload.vswitch_cidr
    if name != "control"
  ]

  shared_tcp_rules = flatten([
    [for name, workload in local.workloads : [
      for cidr in var.model_proxy_cidrs : {
        key      = "${name}-model-${replace(cidr, "/", "_")}"
        workload = name
        cidr     = cidr
        protocol = "tcp"
        ports    = "${var.model_proxy_port}/${var.model_proxy_port}"
      }
    ]],
    [for name, workload in local.workloads : [
      for cidr in var.private_git_cidrs : {
        key      = "${name}-git-${replace(cidr, "/", "_")}"
        workload = name
        cidr     = cidr
        protocol = "tcp"
        ports    = "${var.private_git_port}/${var.private_git_port}"
      }
    ]],
    [for name, workload in local.workloads : [
      for cidr in var.dns_resolver_cidrs : {
        key      = "${name}-dns-${replace(cidr, "/", "_")}"
        workload = name
        cidr     = cidr
        protocol = "tcp"
        ports    = "53/53"
      }
    ]],
    [for name, workload in local.workloads : [
      for cidr in var.time_sync_https_cidrs : {
        key      = "${name}-time-${replace(cidr, "/", "_")}"
        workload = name
        cidr     = cidr
        protocol = "tcp"
        ports    = "443/443"
      }
    ]],
    [for name, workload in local.workloads : [
      for cidr in var.cloud_assistant_cidrs : {
        key      = "${name}-assistant-${replace(cidr, "/", "_")}"
        workload = name
        cidr     = cidr
        protocol = "tcp"
        ports    = "443/443"
      }
    ]],
    [for cidr in var.upstream_model_cidrs : {
      key      = "control-upstream-${replace(cidr, "/", "_")}"
      workload = "control"
      cidr     = cidr
      protocol = "tcp"
      ports    = "${var.upstream_model_port}/${var.upstream_model_port}"
    }]
  ])

  profile_udp_rules = flatten([
    for name, workload in local.workloads : concat(
      workload.network_profile == "direct" ? [
        for cidr in workload.peer_udp_cidrs : {
          key      = "${name}-peer-${replace(cidr, "/", "_")}"
          workload = name
          cidr     = cidr
          protocol = "udp"
          ports    = "1/65535"
        }
      ] : [],
      contains(["direct", "relay-only"], workload.network_profile) ? flatten([
        for cidr in workload.relay_udp_cidrs : [
          for ports in workload.relay_udp_ports : {
            key      = "${name}-relay-${replace(cidr, "/", "_")}-${replace(ports, "/", "_")}"
            workload = name
            cidr     = cidr
            protocol = "udp"
            ports    = ports
          }
        ]
      ]) : []
    )
  ])

  egress_rules = {
    for rule in concat(local.shared_tcp_rules, local.profile_udp_rules) : rule.key => rule
  }
}

resource "alicloud_vpc" "this" {
  for_each   = local.workloads
  vpc_name   = "dsh-${var.run_id}-${each.key}"
  cidr_block = each.value.vpc_cidr

  tags = {
    Project   = "dsh-sandbox"
    RunId     = var.run_id
    Workload  = each.key
    Retention = "retain"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_vswitch" "this" {
  for_each      = local.workloads
  vpc_id        = alicloud_vpc.this[each.key].id
  cidr_block    = each.value.vswitch_cidr
  zone_id       = var.availability_zone
  vswitch_name  = "dsh-${var.run_id}-${each.key}"

  tags = {
    Project  = "dsh-sandbox"
    RunId    = var.run_id
    Workload = each.key
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_nat_gateway" "this" {
  for_each         = local.workloads
  vpc_id           = alicloud_vpc.this[each.key].id
  vswitch_id       = alicloud_vswitch.this[each.key].id
  nat_gateway_name = "dsh-${var.run_id}-${each.key}"
  nat_type         = "Enhanced"
  payment_type     = "PayAsYouGo"

  tags = {
    Project   = "dsh-sandbox"
    RunId     = var.run_id
    Workload  = each.key
    Retention = "retain"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_eip_address" "this" {
  for_each      = local.workloads
  address_name  = "dsh-${var.run_id}-${each.key}"
  bandwidth     = "5"
  internet_charge_type = "PayByTraffic"

  tags = {
    Project  = "dsh-sandbox"
    RunId    = var.run_id
    Workload = each.key
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_eip_association" "this" {
  for_each      = local.workloads
  allocation_id = alicloud_eip_address.this[each.key].id
  instance_id   = alicloud_nat_gateway.this[each.key].id
  instance_type = "Nat"

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_snat_entry" "this" {
  for_each       = local.workloads
  snat_table_id  = split(",", alicloud_nat_gateway.this[each.key].snat_table_ids)[0]
  source_cidr    = each.value.vswitch_cidr
  snat_ip        = alicloud_eip_address.this[each.key].ip_address
  snat_entry_name = "dsh-${var.run_id}-${each.key}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_route_entry" "internet_via_nat" {
  for_each              = local.workloads
  route_table_id        = alicloud_vpc.this[each.key].route_table_id
  destination_cidrblock = "0.0.0.0/0"
  nexthop_type          = "NatGateway"
  nexthop_id            = alicloud_nat_gateway.this[each.key].id

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_security_group" "this" {
  for_each            = local.workloads
  security_group_name = "dsh-${var.run_id}-${each.key}"
  vpc_id              = alicloud_vpc.this[each.key].id
  security_group_type = "normal"
  inner_access_policy = "Drop"

  tags = {
    Project  = "dsh-sandbox"
    RunId    = var.run_id
    Workload = each.key
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_security_group_rule" "deny_unlisted_egress" {
  for_each          = alicloud_security_group.this
  type              = "egress"
  security_group_id = each.value.id
  ip_protocol       = "all"
  port_range        = "-1/-1"
  policy            = "drop"
  priority          = 100
  nic_type          = "intranet"
  cidr_ip           = "0.0.0.0/0"

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_security_group_rule" "control_plane_private_ingress" {
  for_each = {
    for rule in flatten([
      for cidr in local.agent_source_cidrs : [
        { key = "model-${replace(cidr, "/", "_")}", cidr = cidr, ports = "${var.model_proxy_port}/${var.model_proxy_port}" },
        { key = "git-${replace(cidr, "/", "_")}", cidr = cidr, ports = "${var.private_git_port}/${var.private_git_port}" },
      ]
    ]) : rule.key => rule
  }

  type              = "ingress"
  security_group_id = alicloud_security_group.this["control"].id
  ip_protocol       = "tcp"
  port_range        = each.value.ports
  policy            = "accept"
  priority          = 1
  nic_type          = "intranet"
  cidr_ip           = each.value.cidr

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_security_group_rule" "allow_egress" {
  for_each          = local.egress_rules
  type              = "egress"
  security_group_id = alicloud_security_group.this[each.value.workload].id
  ip_protocol       = each.value.protocol
  port_range        = each.value.ports
  policy            = "accept"
  priority          = 1
  nic_type          = "intranet"
  cidr_ip           = each.value.cidr

  lifecycle {
    prevent_destroy = true
  }
}

resource "alicloud_instance" "this" {
  for_each                  = local.workloads
  instance_name             = "dsh-${var.run_id}-${each.key}"
  image_id                  = var.image_id
  instance_type             = each.value.instance_type
  vswitch_id                = alicloud_vswitch.this[each.key].id
  security_groups           = [alicloud_security_group.this[each.key].id]
  internet_max_bandwidth_out = 0
  system_disk_category      = "cloud_essd"
  system_disk_size          = each.value.system_disk_size

  tags = {
    Project     = "dsh-sandbox"
    RunId       = var.run_id
    Workload    = each.key
    ImageDigest = var.image_digest
    Retention   = "retain"
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [
    alicloud_security_group_rule.deny_unlisted_egress,
    alicloud_security_group_rule.allow_egress,
    alicloud_security_group_rule.control_plane_private_ingress,
  ]
}

resource "alicloud_ecs_snapshot" "baseline" {
  for_each       = alicloud_instance.this
  disk_id        = each.value.system_disk_id
  snapshot_name  = "dsh-${var.run_id}-${each.key}-baseline"
  description    = "Retained baseline for DSH sandbox run ${var.run_id}; image digest ${var.image_digest}."

  tags = {
    Project     = "dsh-sandbox"
    RunId       = var.run_id
    Workload    = each.key
    ImageDigest = var.image_digest
    Retention   = "retain"
  }

  lifecycle {
    prevent_destroy = true
  }
}
