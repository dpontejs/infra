output "ipv4" {
  description = "Public IPv4 of the server."
  value       = hcloud_server.main.ipv4_address
}

output "ipv6" {
  description = "Public IPv6 of the server."
  value       = hcloud_server.main.ipv6_address
}

output "ssh" {
  description = "Command to connect to the server (root login is disabled by Ansible, step 03)."
  value       = "ssh -i ~/.ssh/hetzner_vps deploy@${hcloud_server.main.ipv4_address}"
}

output "hostnames" {
  description = "Hostnames pointing to the server."
  value       = sort([for r in cloudflare_dns_record.ipv4 : r.name])
}

output "admin_cidrs" {
  description = "CIDRs allowed into SSH and admin panels (used by Ansible through the generated inventory)."
  value       = var.admin_cidrs
}
