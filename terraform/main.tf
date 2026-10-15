locals {
  labels = {
    project    = "infra"
    managed-by = "terraform"
  }
}

resource "hcloud_ssh_key" "admin" {
  name       = "admin"
  public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
  labels     = local.labels
}

resource "hcloud_firewall" "main" {
  name   = "main"
  labels = local.labels

  rule {
    description = "SSH from admin CIDRs only"
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = var.admin_cidrs
  }

  rule {
    description = "HTTP"
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }

  rule {
    description = "HTTPS"
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }

  rule {
    description = "Ping"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "main" {
  name         = var.server_name
  server_type  = var.server_type
  location     = var.location
  image        = var.image
  ssh_keys     = [hcloud_ssh_key.admin.id]
  firewall_ids = [hcloud_firewall.main.id]
  labels       = local.labels

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  lifecycle {
    # Changing the image would rebuild the server; upgrades go through Ansible instead.
    ignore_changes = [image]
  }
}
