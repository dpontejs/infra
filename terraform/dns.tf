data "cloudflare_zone" "main" {
  filter = {
    name = var.domain
  }
}

locals {
  # "@" is the usual shorthand for the apex: the bare domain, without subdomain.
  hostnames = toset(concat(["@"], var.subdomains))
}

# DNS only (proxied = false): visitors reach the server directly, so Caddy can obtain
# Let's Encrypt certificates on its own. Turning the Cloudflare proxy on is a later decision.
resource "cloudflare_dns_record" "ipv4" {
  for_each = local.hostnames

  zone_id = data.cloudflare_zone.main.id
  name    = each.key == "@" ? var.domain : "${each.key}.${var.domain}"
  type    = "A"
  content = hcloud_server.main.ipv4_address
  ttl     = 300
  proxied = false
  comment = "Managed by Terraform (infra)"
}

resource "cloudflare_dns_record" "ipv6" {
  for_each = local.hostnames

  zone_id = data.cloudflare_zone.main.id
  name    = each.key == "@" ? var.domain : "${each.key}.${var.domain}"
  type    = "AAAA"
  content = hcloud_server.main.ipv6_address
  ttl     = 300
  proxied = false
  comment = "Managed by Terraform (infra)"
}

# Mail is sent as news@<domain> through Resend (SPF and DKIM records were created in the
# Resend setup). Outlook rejects it without a DMARC policy; p=none only asks for alignment
# checks and never blocks anything, which is enough for the providers that require DMARC.
resource "cloudflare_dns_record" "dmarc" {
  zone_id = data.cloudflare_zone.main.id
  name    = "_dmarc.${var.domain}"
  type    = "TXT"
  content = "\"v=DMARC1; p=none;\""
  ttl     = 300
  comment = "Managed by Terraform (infra)"
}
