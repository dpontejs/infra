# Personal Cloud Infrastructure

![Status](https://img.shields.io/badge/status-work%20in%20progress-FFD43B?style=flat-square)
![Terraform](https://img.shields.io/badge/Terraform-844FBA?style=flat-square&logo=terraform&logoColor=white)
![Ansible](https://img.shields.io/badge/Ansible-EE0000?style=flat-square&logo=ansible&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![Caddy](https://img.shields.io/badge/Caddy-1F88C0?style=flat-square&logo=caddy&logoColor=white)
![Cloudflare](https://img.shields.io/badge/Cloudflare-F38020?style=flat-square&logo=cloudflare&logoColor=white)

Infrastructure as code for the small cloud that hosts my projects under **diegoponte.dev**: a Hetzner VPS
provisioned with **Terraform**, configured with **Ansible**, running every service as a **Docker Compose**
stack behind **Caddy** (automatic HTTPS), deployed by **GitHub Actions**, with backups and a
**Cloudflare Tunnel** to expose GPU workloads running on my home machine without opening ports.

## Architecture

```
                    Cloudflare DNS (diegoponte.dev)
                                │
        ┌───────────────────────┴────────────────────────┐
        ▼                                                ▼
  Hetzner VPS (CX23)                             Home PC (RTX 4050)
  ├─ Caddy (HTTPS, reverse proxy)                └─ cloudflared tunnel
  │   ├─ diegoponte.dev        → portfolio           └─ GPU inference / local LLMs
  │   ├─ rag.diegoponte.dev    → RAG demo API
  │   ├─ mlflow.diegoponte.dev → MLflow (auth)
  │   └─ status.diegoponte.dev → Uptime Kuma
  ├─ Postgres + pgvector (shared)
  └─ scheduled jobs (flamengo-news, planning-ai)
```

## Roadmap

Each item is a vertical slice tracked as a GitHub issue.

- [x] **Provisioning with Terraform** — VPS, firewall, SSH key and DNS records as code.
- [x] **Server hardening with Ansible** — SSH keys only, firewall, fail2ban, automatic updates, swap, Docker.
- [x] **Reverse proxy and first services** — Caddy with automatic HTTPS, portfolio and Uptime Kuma.
- [ ] **CI/CD deploy pipeline** — build images to GHCR and deploy to the VPS from GitHub Actions.
- [ ] **Shared database and backups** — Postgres + pgvector, scheduled backups to object storage, tested restore.
- [ ] **Cloudflare Tunnel to the home GPU** — expose GPU services from the home PC securely.

## Learning guide

Each step is documented as a didactic guide: concepts, walkthrough of the code, decisions, exercises and pitfalls.

1. [Provisioning a server with Terraform](docs/guide/01-provisioning-with-terraform.md)
2. [Pointing a domain to the server with Cloudflare DNS](docs/guide/02-dns-with-cloudflare.md)
3. [Hardening and configuring the server with Ansible](docs/guide/03-server-hardening-with-ansible.md)
4. [Reverse proxy and automatic HTTPS with Caddy](docs/guide/04-reverse-proxy-and-https-with-caddy.md)

## Usage

Requirements: Terraform ≥ 1.9, Ansible (`ansible-core` + `ansible-lint`), a Hetzner Cloud project, a domain on Cloudflare and an SSH key.

```bash
# API tokens, kept outside the repo (chmod 600)
#   HCLOUD_TOKEN: Hetzner project token (Read & Write)
#   CLOUDFLARE_API_TOKEN: Zone:Read + DNS:Edit on the domain's zone only
echo 'export HCLOUD_TOKEN=...' > ~/.config/infra/secrets.env
echo 'export CLOUDFLARE_API_TOKEN=...' >> ~/.config/infra/secrets.env

cp terraform/example.tfvars terraform/terraform.tfvars   # set admin_cidrs to your IP
make init
make plan    # review what will change
make apply   # apply exactly the reviewed plan

make bootstrap   # first Ansible run, as root; disables root login at the end
make configure   # every later run, as the deploy user (also deploys the stacks)
make smoke       # check the live sites
```

| Command | What it does |
|---|---|
| `make test` | Terraform tests with mocked providers (no cloud calls) + Ansible syntax check + stack validation (Compose, Caddyfile) |
| `make lint` | `terraform fmt -check` + `terraform validate` + `ansible-lint` (production profile) + `caddy fmt` |
| `make plan` / `make apply` | Plan to a file, then apply that exact plan |
| `make bootstrap` / `make configure` | Configure the server with Ansible (first run as root / later runs as `deploy`) |
| `make check` | Ansible dry run: shows what would change |
| `make smoke` | Checks the live sites after a deploy (HTTPS, redirects, headers, admin panel) |

SSH is only reachable from `admin_cidrs`. If your home IP changes, update `terraform.tfvars` and run
`make plan && make apply` again.

## Budget

Target: under R$ 50/month (VPS ~€6/month + domain ~US$ 12/year; Cloudflare DNS, Tunnel and R2 free tier).

## License

MIT
