# 02 — Pointing a domain to the server with Cloudflare DNS

> **Goal of this step:** make `diegoponte.dev` and its subdomains resolve to the server created in
> [step 01](01-provisioning-with-terraform.md), managed as code in the same Terraform project.
>
> **Files:** [`terraform/dns.tf`](../../terraform/dns.tf) · **Issue:** #1

## 1. What DNS does

Computers talk using IP addresses (`203.0.113.10`, `2001:db8::1`). People prefer names
(`diegoponte.dev`). **DNS** is the internet's phone book that translates one into the other.

```
browser: "where is rag.diegoponte.dev?"
   │
   ├─► resolver (your ISP, 1.1.1.1, 8.8.8.8…)
   │      ├─► root servers:      "ask the .dev servers"
   │      ├─► .dev servers:      "ask Cloudflare (anna/neil.ns.cloudflare.com)"
   │      └─► Cloudflare:        "A 203.0.113.10, AAAA 2001:db8::1"
   │
   └─► connects to 203.0.113.10:443
```

When the domain was bought, the registry was told that Cloudflare's **nameservers** are authoritative for
`diegoponte.dev`. From then on, whatever records exist in the Cloudflare zone are the truth.

## 2. Record types used here

| Type | Maps a name to | Example |
|---|---|---|
| **A** | an IPv4 address | `diegoponte.dev → 203.0.113.10` |
| **AAAA** | an IPv6 address | `diegoponte.dev → 2001:db8::1` |

Other common types you'll meet later: **CNAME** (alias to another name), **MX** (mail servers),
**TXT** (verification strings, SPF/DKIM for email).

**Apex** (or root) is the bare domain, `diegoponte.dev`, written as `@` in many DNS panels.
**Subdomains** are labels on the left: `www`, `status`, `rag`, `mlflow`.

**TTL** (time to live, in seconds) is how long resolvers may cache an answer. We use `300` (5 minutes):
short enough that a change (e.g. a new server IP) propagates quickly.

## 3. Walkthrough of `dns.tf`

### Finding the zone

```hcl
data "cloudflare_zone" "main" {
  filter = { name = var.domain }
}
```

A **data source** *reads* something that already exists instead of creating it. The zone was created
when the domain was bought; Terraform only needs its ID. This is why the API token has `Zone:Read`
in addition to `DNS:Edit`.

### One record per hostname, with `for_each`

```hcl
locals {
  hostnames = toset(concat(["@"], var.subdomains))   # ["@", "www", "status", "rag", "mlflow"]
}

resource "cloudflare_dns_record" "ipv4" {
  for_each = local.hostnames
  name     = each.key == "@" ? var.domain : "${each.key}.${var.domain}"
  content  = hcloud_server.main.ipv4_address
  ...
}
```

`for_each` creates **one resource instance per element**, addressed by key:
`cloudflare_dns_record.ipv4["rag"]`. Adding a subdomain to the list creates exactly one new record and
touches nothing else. (With `count`, removing an item from the middle of a list would shift the indexes and
recreate records.)

`content = hcloud_server.main.ipv4_address` is a **cross-provider reference**: the Hetzner server's IP
feeds the Cloudflare record. Terraform creates the server first, then the records — and if the server is
ever recreated with a new IP, the next `apply` updates DNS automatically.

### Why `proxied = false`

Cloudflare can work in two modes per record:

| | DNS only (grey cloud) — **used here** | Proxied (orange cloud) |
|---|---|---|
| DNS answer | the server's real IP | a Cloudflare IP |
| Traffic path | visitor → server | visitor → Cloudflare → server |
| HTTPS certificate | issued by Caddy on the server (Let's Encrypt) | Cloudflare's edge cert + origin config |
| Extras | — | CDN cache, DDoS protection, hides the server IP |

DNS only keeps the setup simple and lets Caddy (step 04) get certificates by itself. Turning the proxy on
later is a one-line change plus choosing Cloudflare's "Full (strict)" SSL mode.

### Validation

`subdomains` only accepts lowercase DNS labels (`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`), so a typo like
`Not_Valid` fails at plan time instead of producing a broken record.

## 4. Tests

[`tests/dns.tftest.hcl`](../../terraform/tests/dns.tftest.hcl) mocks both providers and uses
`command = apply` so computed values (the server IPs) exist inside the test:

- `override_resource` pins the server's IPs (`198.51.100.10`, `2001:db8::1` — addresses reserved for
  documentation) and numeric IDs for the firewall and SSH key (mocks would otherwise invent random strings).
- `override_data` returns a fake zone ID.

The assertions check that every hostname gets both A and AAAA records with the server IPs, in the right
zone, never proxied, and that invalid subdomains are rejected.

## 5. Verifying for real

After `make apply`:

```bash
dig +short diegoponte.dev A          # → server IPv4
dig +short rag.diegoponte.dev AAAA   # → server IPv6
dig diegoponte.dev NS +short         # → anna/neil.ns.cloudflare.com
dig @1.1.1.1 diegoponte.dev          # ask a specific resolver
```

No `dig`? `nslookup diegoponte.dev` works too (also on Windows).

Note: `.dev` is on the browsers' **HSTS preload list** — browsers only open it over HTTPS. Until Caddy
is running (step 04), opening `https://diegoponte.dev` fails even though DNS is correct. That's expected.

## 6. Exercises

1. Add `"blog"` to `subdomains` in `terraform.tfvars`, run `make plan` and count how many resources are
   added. Why two?
2. Run `dig +trace diegoponte.dev` and match each step to the diagram in section 1.
3. Change `ttl` to `60`, plan, and read how Terraform shows an in-place update (`~`).
4. Find in the Cloudflare panel the records created by Terraform. What does the "comment" field say?
5. Write a test asserting that every record has `ttl == 300`.

## 7. Pitfalls

- **Editing records by hand in the panel** creates drift; the next `apply` reverts it. Change the code instead.
- **Negative caching:** if you query a name *before* it exists, resolvers may cache the "doesn't exist"
  answer for a while. If a new record doesn't resolve, wait a few minutes or query `@1.1.1.1` directly.
- **Proxy + Let's Encrypt HTTP challenge** don't mix out of the box: if you flip a record to proxied,
  configure Cloudflare SSL mode first.

## Further reading

- [How DNS works (Cloudflare Learning)](https://www.cloudflare.com/learning/dns/what-is-dns/)
- [Proxied vs DNS-only records](https://developers.cloudflare.com/dns/proxy-status/)
- [cloudflare_dns_record resource](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/dns_record)
- [Terraform `for_each`](https://developer.hashicorp.com/terraform/language/meta-arguments/for_each)
