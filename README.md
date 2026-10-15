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

- [ ] **Provisioning with Terraform** — VPS, firewall, SSH key and DNS records as code.
- [ ] **Server hardening with Ansible** — SSH keys only, firewall, fail2ban, automatic updates, swap, Docker.
- [ ] **Reverse proxy and first services** — Caddy with automatic HTTPS, portfolio and Uptime Kuma.
- [ ] **CI/CD deploy pipeline** — build images to GHCR and deploy to the VPS from GitHub Actions.
- [ ] **Shared database and backups** — Postgres + pgvector, scheduled backups to object storage, tested restore.
- [ ] **Cloudflare Tunnel to the home GPU** — expose GPU services from the home PC securely.

## Usage

Requirements: Terraform ≥ 1.9, a Hetzner Cloud project and an SSH key.

```bash
# Hetzner API token, kept outside the repo (chmod 600)
echo 'export HCLOUD_TOKEN=...' > ~/.config/infra/secrets.env

cp terraform/example.tfvars terraform/terraform.tfvars   # set admin_cidrs to your IP
make init
make plan    # review what will change
make apply   # apply exactly the reviewed plan
```

| Command | What it does |
|---|---|
| `make test` | Terraform tests with a mocked provider (no cloud calls) |
| `make lint` | `terraform fmt -check` + `terraform validate` |
| `make plan` / `make apply` | Plan to a file, then apply that exact plan |

SSH is only reachable from `admin_cidrs`. If your home IP changes, update `terraform.tfvars` and run
`make plan && make apply` again.

## Budget

Target: under R$ 50/month (VPS ~€6/month + domain ~US$ 12/year; Cloudflare DNS, Tunnel and R2 free tier).

## License

MIT
