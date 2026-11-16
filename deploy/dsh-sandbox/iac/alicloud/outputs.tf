output "workload_inventory" {
  description = "Provider inventory matching the three-agent validator shape. Runtime path evidence is separate."
  value = {
    run_id = var.run_id
    agents = [
      for name in ["front", "back", "integration"] : {
        agent_id               = name
        egress_network_id      = alicloud_nat_gateway.this[name].id
        public_ip              = alicloud_eip_address.this[name].ip_address
        subnet_id              = alicloud_vswitch.this[name].id
        inbound_ports          = []
        public_control_endpoint = false
        network_profile        = local.workloads[name].network_profile
        network_policy = {
          peer_udp  = local.workloads[name].network_profile == "direct"
          relay_udp = contains(["direct", "relay-only"], local.workloads[name].network_profile)
        }
        lifecycle = {
          instance_id = alicloud_instance.this[name].id
          run_id      = var.run_id
          state       = alicloud_instance.this[name].status
          created_at  = alicloud_instance.this[name].create_time
          expires_at  = var.run_expires_at
          deallocation = {
            run_id             = var.run_id
            mode               = "stop"
            preserve_disks     = true
            preserve_snapshots = true
            preserve_evidence  = true
            preview_required   = true
          }
        }
        snapshot = {
          snapshot_id     = alicloud_ecs_snapshot.baseline[name].id
          created_at      = alicloud_ecs_snapshot.baseline[name].create_time
          source_image_id = var.image_id
          image_digest    = var.image_digest
        }
      }
    ]
  }
}

output "control_plane_inventory" {
  description = "Control-plane inventory kept separate from the three-member provider contract."
  value = {
    instance_id     = alicloud_instance.this["control"].id
    system_disk_id  = alicloud_instance.this["control"].system_disk_id
    vpc_id          = alicloud_vpc.this["control"].id
    subnet_id       = alicloud_vswitch.this["control"].id
    nat_gateway_id  = alicloud_nat_gateway.this["control"].id
    egress_ip       = alicloud_eip_address.this["control"].ip_address
    snapshot_id     = alicloud_ecs_snapshot.baseline["control"].id
    image_id        = var.image_id
    image_digest    = var.image_digest
  }
}
