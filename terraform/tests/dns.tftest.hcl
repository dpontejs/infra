# With `command = apply`, mocks invent random string IDs; the server expects numeric
# firewall/SSH key IDs, so they are pinned here.
mock_provider "hcloud" {
  override_resource {
    target = hcloud_firewall.main
    values = { id = "101" }
  }

  override_resource {
    target = hcloud_ssh_key.admin
    values = { id = "202" }
  }

  override_resource {
    target = hcloud_server.main
    values = {
      ipv4_address = "198.51.100.10"
      ipv6_address = "2001:db8::1"
    }
  }
}

mock_provider "cloudflare" {
  override_data {
    target = data.cloudflare_zone.main
    values = {
      id = "zone-123"
    }
  }
}

variables {
  admin_cidrs         = ["203.0.113.10/32"]
  ssh_public_key_path = "tests/fixtures/test_key.pub"
}

run "apex_and_subdomains_point_to_the_server" {
  command = apply

  assert {
    condition = toset([for r in cloudflare_dns_record.ipv4 : r.name]) == toset([
      "diegoponte.dev", "www.diegoponte.dev", "status.diegoponte.dev",
      "rag.diegoponte.dev", "mlflow.diegoponte.dev", "flamengo.diegoponte.dev",
      "urubunews.diegoponte.dev", "edutoria.diegoponte.dev", "today.diegoponte.dev",
      "geral.diegoponte.dev", "hachibu.diegoponte.dev", "monitor.diegoponte.dev", "deploys.diegoponte.dev",
    ])
    error_message = "A records must cover the apex and every subdomain"
  }

  assert {
    condition     = alltrue([for r in cloudflare_dns_record.ipv4 : r.type == "A" && r.content == "198.51.100.10"])
    error_message = "A records must point to the server IPv4"
  }

  assert {
    condition     = alltrue([for r in cloudflare_dns_record.ipv6 : r.type == "AAAA" && r.content == "2001:db8::1"])
    error_message = "AAAA records must point to the server IPv6"
  }

  # Every hostname has both records, except the admin panels (IPv4 only, see admin_panels_are_ipv4_only).
  assert {
    condition = toset([for r in cloudflare_dns_record.ipv6 : r.name]) == setsubtract(
      toset([for r in cloudflare_dns_record.ipv4 : r.name]),
      toset(["status.diegoponte.dev", "monitor.diegoponte.dev", "deploys.diegoponte.dev"]),
    )
    error_message = "Every hostname but the admin panels needs both A and AAAA records"
  }

  assert {
    condition     = alltrue([for r in concat(values(cloudflare_dns_record.ipv4), values(cloudflare_dns_record.ipv6)) : r.zone_id == "zone-123"])
    error_message = "Records must be created in the domain's zone"
  }
}

run "records_are_dns_only_so_caddy_can_issue_certificates" {
  command = apply

  assert {
    condition     = alltrue([for r in concat(values(cloudflare_dns_record.ipv4), values(cloudflare_dns_record.ipv6)) : r.proxied == false])
    error_message = "Records must not be proxied by Cloudflare"
  }
}

run "custom_subdomains" {
  command = apply

  variables {
    subdomains = ["api"]
  }

  assert {
    condition     = toset(keys(cloudflare_dns_record.ipv4)) == toset(["@", "api"])
    error_message = "Only the apex and the given subdomains must get records"
  }
}

run "rejects_invalid_subdomain" {
  command = plan

  variables {
    subdomains = ["Not_Valid"]
  }

  expect_failures = [var.subdomains]
}

# Outlook rejects mail without DMARC (550 5.7.1 "lacks SPF/DKIM/DMARC Auth Records").
run "domain_publishes_a_dmarc_policy" {
  command = apply

  assert {
    condition     = cloudflare_dns_record.dmarc.name == "_dmarc.diegoponte.dev" && cloudflare_dns_record.dmarc.type == "TXT"
    error_message = "DMARC must be a TXT record at _dmarc.<domain>"
  }

  assert {
    condition     = startswith(trim(cloudflare_dns_record.dmarc.content, "\""), "v=DMARC1; p=none;")
    error_message = "DMARC must start with v=DMARC1 and a monitoring-only policy (p=none)"
  }
}

# The admin's home IPv6 prefix changes almost daily while the IPv4 stays: without AAAA records the
# browser reaches the admin panels over IPv4, the address ADMIN_CIDRS can rely on.
run "admin_panels_are_ipv4_only" {
  command = apply

  assert {
    condition = length(setintersection(
      toset([for r in cloudflare_dns_record.ipv6 : r.name]),
      toset(["status.diegoponte.dev", "monitor.diegoponte.dev", "deploys.diegoponte.dev"]),
    )) == 0
    error_message = "Admin panels must have no AAAA record"
  }

  assert {
    condition = length(setsubtract(
      toset(["status.diegoponte.dev", "monitor.diegoponte.dev", "deploys.diegoponte.dev"]),
      toset([for r in cloudflare_dns_record.ipv4 : r.name]),
    )) == 0
    error_message = "Admin panels must keep their A record"
  }

  assert {
    condition     = contains([for r in cloudflare_dns_record.ipv6 : r.name], "geral.diegoponte.dev")
    error_message = "Public sites keep their AAAA record"
  }
}
