terraform {
  required_version = ">= 1.9"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.70"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.28"
    }
  }
}

# Token comes from the HCLOUD_TOKEN environment variable.
provider "hcloud" {}

# Token comes from the CLOUDFLARE_API_TOKEN environment variable.
provider "cloudflare" {}
