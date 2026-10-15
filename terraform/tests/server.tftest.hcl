mock_provider "hcloud" {}

variables {
  admin_cidrs         = ["203.0.113.10/32"]
  ssh_public_key_path = "tests/fixtures/test_key.pub"
}

run "defaults_create_cx23_in_nuremberg" {
  command = plan

  assert {
    condition     = hcloud_server.main.server_type == "cx23" && hcloud_server.main.location == "nbg1"
    error_message = "Default server must be a CX23 in Nuremberg"
  }

  assert {
    condition     = hcloud_server.main.image == "ubuntu-24.04"
    error_message = "Default image must be Ubuntu 24.04"
  }

  assert {
    condition     = alltrue([for net in hcloud_server.main.public_net : net.ipv4_enabled && net.ipv6_enabled])
    error_message = "Server must have public IPv4 and IPv6"
  }
}

run "firewall_restricts_ssh_to_admin_cidrs" {
  command = plan

  assert {
    condition = alltrue([
      for rule in hcloud_firewall.main.rule :
      toset(rule.source_ips) == toset(["203.0.113.10/32"])
      if rule.port == "22"
    ])
    error_message = "SSH must only be reachable from admin_cidrs"
  }

  assert {
    condition = length([
      for rule in hcloud_firewall.main.rule : rule
      if contains(["80", "443"], coalesce(rule.port, "none")) && contains(rule.source_ips, "0.0.0.0/0")
    ]) == 2
    error_message = "HTTP and HTTPS must be open to the internet"
  }
}

run "ssh_key_comes_from_file" {
  command = plan

  assert {
    condition     = hcloud_ssh_key.admin.public_key == trimspace(file("tests/fixtures/test_key.pub"))
    error_message = "SSH key must be read from ssh_public_key_path"
  }
}

run "rejects_ssh_open_to_the_world" {
  command = plan

  variables {
    admin_cidrs = ["0.0.0.0/0"]
  }

  expect_failures = [var.admin_cidrs]
}

run "rejects_empty_admin_cidrs" {
  command = plan

  variables {
    admin_cidrs = []
  }

  expect_failures = [var.admin_cidrs]
}
