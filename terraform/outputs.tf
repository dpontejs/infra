output "ipv4" {
  description = "Public IPv4 of the server."
  value       = hcloud_server.main.ipv4_address
}

output "ipv6" {
  description = "Public IPv6 of the server."
  value       = hcloud_server.main.ipv6_address
}

output "ssh" {
  description = "Command to connect to the server."
  value       = "ssh -i ~/.ssh/hetzner_vps root@${hcloud_server.main.ipv4_address}"
}
