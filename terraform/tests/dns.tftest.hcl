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

  assert {
    condition     = length(cloudflare_dns_record.ipv6) == length(cloudflare_dns_record.ipv4)
    error_message = "Every hostname needs both A and AAAA records"
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
