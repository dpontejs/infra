variable "admin_cidrs" {
  description = "CIDRs allowed to reach SSH (port 22), e.g. your home IP as x.x.x.x/32."
  type        = list(string)

  validation {
    condition     = length(var.admin_cidrs) > 0
    error_message = "admin_cidrs must have at least one CIDR, otherwise SSH is unreachable."
  }

  validation {
    condition     = alltrue([for cidr in var.admin_cidrs : !contains(["0.0.0.0/0", "::/0"], cidr)])
    error_message = "SSH must not be open to the whole internet; use specific CIDRs."
  }
}

variable "ssh_public_key_path" {
  description = "Path to the public SSH key installed on the server."
  type        = string
  default     = "~/.ssh/hetzner_vps.pub"
}

variable "server_name" {
  description = "Server hostname."
  type        = string
  default     = "vps-01"
}

variable "server_type" {
  description = "Hetzner server type (cx23 = 2 vCPU, 4 GB RAM, 40 GB disk)."
  type        = string
  default     = "cx23"
}

variable "location" {
  description = "Hetzner location (nbg1 = Nuremberg)."
  type        = string
  default     = "nbg1"
}

variable "image" {
  description = "OS image."
  type        = string
  default     = "ubuntu-24.04"
}

variable "domain" {
  description = "Domain managed in Cloudflare."
  type        = string
  default     = "diegoponte.dev"
}

variable "subdomains" {
  description = "Subdomains that point to the server, besides the apex (the domain itself)."
  type        = list(string)
  default     = ["www", "status", "rag", "mlflow", "flamengo", "urubunews", "edutoria"]

  validation {
    condition     = alltrue([for s in var.subdomains : can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", s))])
    error_message = "Subdomains must be lowercase DNS labels (letters, digits and hyphens)."
  }
}
