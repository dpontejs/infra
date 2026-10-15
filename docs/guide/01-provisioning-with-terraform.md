# 01 — Provisioning a server with Terraform

> **Goal of this step:** create a VPS, its firewall and SSH access on Hetzner Cloud **from code**, so the
> whole server can be destroyed and recreated with one command.
>
> **Files:** [`terraform/`](../../terraform) · **PR:** #7 · **Issue:** #1

## 1. The problem

You could click "Create server" in the Hetzner console. It works once — but then nobody (including
future you) knows exactly how the server was configured, and recreating it means remembering every click.

**Infrastructure as Code (IaC)** solves this: the infrastructure is described in text files, versioned in
Git, reviewed in pull requests and applied by a tool. The files *are* the documentation.

## 2. Core concepts

| Concept | In plain words | Where in this repo |
|---|---|---|
| **Provider** | Plugin that talks to one platform's API (Hetzner, Cloudflare, AWS…) | `versions.tf` |
| **Resource** | One thing that should exist (a server, a firewall, an SSH key) | `main.tf` |
| **Variable** | An input, so the same code works with different values | `variables.tf` |
| **Output** | A value printed after apply (e.g. the server IP) | `outputs.tf` |
| **State** | Terraform's memory of what it created, mapping code ↔ real resources | `terraform.tfstate` (local, gitignored) |
| **Plan** | A preview: what Terraform *would* create, change or destroy | `make plan` |
| **Apply** | Executes the plan against the real API | `make apply` |

Terraform is **declarative**: you describe the *desired end state* ("there is one CX23 server"), not the
steps. On every run Terraform compares code, state and reality, and computes the difference.

```
 code (.tf)  ──┐
               ├─►  terraform plan  ──►  diff  ──►  terraform apply  ──►  Hetzner API
 state  ───────┘                                          │
                                                          └──► updates state
```

## 3. Walkthrough of the files

### `versions.tf` — which tools and versions

```hcl
required_providers {
  hcloud = { source = "hetznercloud/hcloud", version = "~> 1.70" }
}
```

`~> 1.70` means "1.70 or newer, but below 2.0": you get bug fixes, not breaking changes. The exact version
downloaded is pinned in `.terraform.lock.hcl` (committed), so CI and your machine use the same provider.

The provider block is empty because the API token comes from the `HCLOUD_TOKEN` **environment variable**.
Secrets never go in `.tf` files — those are committed to Git.

### `variables.tf` — inputs and guard rails

Most variables have sensible defaults (`cx23`, `nbg1`, `ubuntu-24.04`). `admin_cidrs` has **no default**:
you must say which IPs may use SSH. It also has **validations**:

```hcl
validation {
  condition     = alltrue([for cidr in var.admin_cidrs : !contains(["0.0.0.0/0", "::/0"], cidr)])
  error_message = "SSH must not be open to the whole internet; use specific CIDRs."
}
```

A validation turns a dangerous mistake into an error *before* anything is created.

> **CIDR in 30 seconds:** `203.0.113.10/32` means "exactly this one IP" (all 32 bits fixed).
> `0.0.0.0/0` means "every IPv4 address". `::/0` is the same for IPv6.

### `main.tf` — the resources

1. **`hcloud_ssh_key.admin`** uploads your *public* key. The private key never leaves your machine.
   Hetzner installs it for `root` and, because a key was provided, does not create a root password.
2. **`hcloud_firewall.main`** is a cloud firewall: it filters traffic *before* it reaches the server, so
   even a misconfigured service inside can't be reached on a closed port.
   - `22` (SSH): only from `admin_cidrs`
   - `80` / `443` (HTTP/HTTPS): open — the web server lives here
   - ICMP (ping): open, useful for diagnostics
3. **`hcloud_server.main`** references the other two by ID (`hcloud_ssh_key.admin.id`). These references
   are how Terraform learns the **dependency order**: key and firewall first, then the server.

`lifecycle { ignore_changes = [image] }` exists because changing the image of an existing server would
force Terraform to **destroy and recreate** it. OS updates are handled inside the server (step 02).

### `outputs.tf`

After `apply`, Terraform prints the IPs and a ready-to-copy SSH command. Read them anytime with
`terraform -chdir=terraform output`.

## 4. Testing infrastructure code

`terraform/tests/server.tftest.hcl` uses **`terraform test`** with `mock_provider "hcloud" {}`: the
provider is replaced by a fake, so tests run in seconds, cost nothing and need no token. They check
*our* logic — defaults, firewall rules, validations — not Hetzner's API.

```hcl
run "rejects_ssh_open_to_the_world" {
  command   = plan
  variables { admin_cidrs = ["0.0.0.0/0"] }
  expect_failures = [var.admin_cidrs]   # the test passes only if validation fails
}
```

CI (`.github/workflows/ci.yml`) runs `make lint` (format + validate) and `make test` on every PR.

## 5. Running it

```bash
make init    # download the provider
make plan    # preview, saved to terraform/tfplan
make apply   # apply exactly that saved plan
```

Saving the plan to a file and applying *that file* guarantees that what you reviewed is what runs —
nothing changes between review and execution.

## 6. Exercises

Try these after the server exists. Always run `make plan` and **read** the output before applying.

1. **Resize:** set `server_type = "cx33"` in `terraform.tfvars` and run `make plan`. Is it an update in
   place (`~`) or a replacement (`-/+`)? (Revert without applying — CX33 costs more.)
2. **Break the guard rail:** set `admin_cidrs = ["0.0.0.0/0"]` and run `make plan`. Read the error.
3. **Drift:** in the Hetzner console, add a rule to the firewall by hand. Run `make plan`. Terraform
   detects the *drift* and proposes removing it — the code is the source of truth.
4. **Inspect state:** run `terraform -chdir=terraform state list` and
   `terraform -chdir=terraform state show hcloud_server.main`.
5. **Write a test:** add a `run` block asserting that the server has the `managed-by = "terraform"` label.

## 7. Pitfalls

- **Never commit state or tfvars.** State can contain sensitive data; `.gitignore` already excludes
  `*.tfstate` and `*.tfvars`.
- **Losing the state file** means Terraform forgets what it created (resources keep running and billing).
  For now it lives only in `terraform/terraform.tfstate` on this machine — step 05 moves it to remote storage.
- **Your home IP changes.** When SSH suddenly times out, check `curl -s https://ifconfig.me`, update
  `admin_cidrs` and re-apply. Emergency access: the web console in the Hetzner panel.
- **`destroy` is real.** `terraform destroy` deletes the server and its disk. There is no undo.

## Further reading

- [Terraform: Get Started](https://developer.hashicorp.com/terraform/tutorials)
- [Terraform tests](https://developer.hashicorp.com/terraform/language/tests)
- [hcloud provider docs](https://registry.terraform.io/providers/hetznercloud/hcloud/latest/docs)
- [Hetzner Cloud firewalls](https://docs.hetzner.com/cloud/firewalls/)
