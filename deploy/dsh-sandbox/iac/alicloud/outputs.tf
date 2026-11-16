output "workload_inventory" {
  description = "Provider inventory metadata. This is not runtime evidence of observed egress or selected P2P path."
  value = {
    for name, workload in local.workloads : name => {
      region              = var.region
      instance_id         = alicloud_instance.this[name].id
      system_disk_id      = alicloud_instance.this[name].system_disk_id
      vpc_id              = alicloud_vpc.this[name].id
      subnet_id           = alicloud_vswitch.this[name].id
      nat_gateway_id      = alicloud_nat_gateway.this[name].id
      egress_network_id   = alicloud_nat_gateway.this[name].id
      public_egress_ip    = alicloud_eip_address.this[name].ip_address
      snapshot_id         = alicloud_snapshot.baseline[name].id
      image_id            = var.image_id
      image_digest        = var.image_digest
      network_profile     = workload.network_profile
      inbound_ports       = []
      public_control_endpoint = false
      lifecycle = {
        run_id           = var.run_id
        instance_id      = alicloud_instance.this[name].id
        deallocation_mode = "stop"
        preserve_disks   = true
        preserve_snapshots = true
        preserve_evidence  = true
        preview_required   = true
      }
    }
  }
}
