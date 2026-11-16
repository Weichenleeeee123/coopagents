variable "region" {
  description = "Alibaba Cloud region. Singapore is the default; override for another approved region."
  type        = string
  default     = "ap-southeast-1"
}

variable "availability_zone" {
  description = "An availability zone in region with the selected instance types and image available."
  type        = string
}

variable "run_id" {
  description = "Unique, non-secret identifier for this sandbox run."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,62}$", var.run_id))
    error_message = "run_id must be a 1-63 character alphanumeric or hyphen identifier."
  }
}

variable "image_id" {
  description = "Exact Alibaba Cloud ECS image ID for the pinned Linux image."
  type        = string
}

variable "image_digest" {
  description = "SHA-256 digest recorded for the pinned image build."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be sha256 followed by 64 lowercase hexadecimal characters."
  }
}

variable "workloads" {
  description = "Four isolated ECS workloads. Use only synthetic run data; profile endpoints must be narrowly scoped."
  type = object({
    front = object({
      instance_type    = string
      system_disk_size = number
      vpc_cidr         = string
      vswitch_cidr     = string
      network_profile  = string
      peer_udp_cidrs   = list(string)
      relay_udp_cidrs  = list(string)
      relay_udp_ports  = list(string)
    })
    back = object({
      instance_type    = string
      system_disk_size = number
      vpc_cidr         = string
      vswitch_cidr     = string
      network_profile  = string
      peer_udp_cidrs   = list(string)
      relay_udp_cidrs  = list(string)
      relay_udp_ports  = list(string)
    })
    integration = object({
      instance_type    = string
      system_disk_size = number
      vpc_cidr         = string
      vswitch_cidr     = string
      network_profile  = string
      peer_udp_cidrs   = list(string)
      relay_udp_cidrs  = list(string)
      relay_udp_ports  = list(string)
    })
    control = object({
      instance_type    = string
      system_disk_size = number
      vpc_cidr         = string
      vswitch_cidr     = string
      network_profile  = string
      peer_udp_cidrs   = list(string)
      relay_udp_cidrs  = list(string)
      relay_udp_ports  = list(string)
    })
  })

  validation {
    condition = alltrue([
      for name, workload in var.workloads :
      contains(["direct", "relay-only", "udp-blocked"], workload.network_profile) &&
      (workload.network_profile != "direct" || (length(workload.peer_udp_cidrs) > 0 && length(workload.relay_udp_cidrs) > 0 && length(workload.relay_udp_ports) > 0)) &&
      (workload.network_profile != "relay-only" || (length(workload.peer_udp_cidrs) == 0 && length(workload.relay_udp_cidrs) > 0 && length(workload.relay_udp_ports) > 0)) &&
      (workload.network_profile != "udp-blocked" || (length(workload.peer_udp_cidrs) == 0 && length(workload.relay_udp_cidrs) == 0 && length(workload.relay_udp_ports) == 0)) &&
      (name != "control" || workload.network_profile == "udp-blocked") &&
      workload.system_disk_size >= 40 && workload.system_disk_size <= 2048 &&
      can(cidrhost(workload.vpc_cidr, 0)) && can(cidrhost(workload.vswitch_cidr, 0))
    ])
    error_message = "Each workload needs a valid profile, CIDRs, and 40-2048 GiB boot disk; direct needs peer and relay endpoints, relay-only needs relay endpoints, udp-blocked has none, and control must be udp-blocked."
  }

  validation {
    condition = length(toset([for workload in values(var.workloads) : workload.vpc_cidr])) == 4 &&
      length(toset([for workload in values(var.workloads) : workload.vswitch_cidr])) == 4
    error_message = "All four workloads must use distinct VPC and VSwitch CIDRs."
  }
}

variable "model_proxy_cidrs" {
  description = "Private CIDRs for the control-plane model proxy, reachable only through the operator's private routing."
  type        = list(string)

  validation {
    condition     = length(var.model_proxy_cidrs) > 0 && alltrue([for cidr in var.model_proxy_cidrs : can(cidrhost(cidr, 0))])
    error_message = "model_proxy_cidrs must contain valid, narrowly scoped CIDRs."
  }
}

variable "model_proxy_port" {
  description = "TCP port exposed by the private model proxy."
  type        = number
  default     = 8443
}

variable "private_git_cidrs" {
  description = "Private CIDRs for the synthetic Git service, reachable only through the operator's private routing."
  type        = list(string)

  validation {
    condition     = length(var.private_git_cidrs) > 0 && alltrue([for cidr in var.private_git_cidrs : can(cidrhost(cidr, 0))])
    error_message = "private_git_cidrs must contain valid, narrowly scoped CIDRs."
  }
}

variable "private_git_port" {
  description = "TCP port exposed by the private Git service."
  type        = number
  default     = 443
}

variable "dns_resolver_cidrs" {
  description = "Explicit DNS resolver CIDRs. TCP DNS is used so the UDP-blocked profile blocks all UDP."
  type        = list(string)

  validation {
    condition     = length(var.dns_resolver_cidrs) > 0 && alltrue([for cidr in var.dns_resolver_cidrs : can(cidrhost(cidr, 0))])
    error_message = "dns_resolver_cidrs must contain valid resolver CIDRs."
  }
}

variable "time_sync_https_cidrs" {
  description = "CIDRs for an approved HTTPS time source; keeps the udp-blocked profile free of UDP exceptions."
  type        = list(string)

  validation {
    condition     = length(var.time_sync_https_cidrs) > 0 && alltrue([for cidr in var.time_sync_https_cidrs : can(cidrhost(cidr, 0))])
    error_message = "time_sync_https_cidrs must contain valid HTTPS time-source CIDRs."
  }
}

variable "cloud_assistant_cidrs" {
  description = "Regional Cloud Assistant endpoint CIDRs used for outbound-only private management."
  type        = list(string)

  validation {
    condition     = length(var.cloud_assistant_cidrs) > 0 && alltrue([for cidr in var.cloud_assistant_cidrs : can(cidrhost(cidr, 0))])
    error_message = "cloud_assistant_cidrs must contain valid Cloud Assistant endpoint CIDRs."
  }
}

variable "upstream_model_cidrs" {
  description = "Narrow upstream model endpoint CIDRs for the control-plane proxy only."
  type        = list(string)
  default     = []
}

variable "upstream_model_port" {
  description = "TCP port used by the control-plane model proxy to reach its configured upstream."
  type        = number
  default     = 443
}
