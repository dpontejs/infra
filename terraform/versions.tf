terraform {
  required_version = ">= 1.9"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.70"
    }
  }
}

# Token comes from the HCLOUD_TOKEN environment variable.
provider "hcloud" {}
