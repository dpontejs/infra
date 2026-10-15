# 04 — Reverse proxy and automatic HTTPS with Caddy

> **Goal of this step:** serve `https://diegoponte.dev` with a valid certificate, redirect `www`, and put
> an admin panel (Uptime Kuma) at `status.diegoponte.dev` — all as Docker Compose stacks deployed by Ansible.
>
> **Files:** [`stacks/`](../../stacks) · [`ansible/roles/stacks/`](../../ansible/roles/stacks) ·
> [`scripts/smoke.sh`](../../scripts/smoke.sh) · **Issue:** #3

## 1. Why a reverse proxy

One server, many services, but only **one** port 443. A **reverse proxy** sits in front, receives every
request and forwards it to the right service based on the hostname:

```
                         ┌──────────── VPS ─────────────────────────────────┐
 https://diegoponte.dev ─┤                                                  │
 https://www.…          ─┤  Caddy :443 ──► /srv/portfolio (static files)    │
 https://status.…       ─┤        │                                         │
                         │        └──────► uptime-kuma:3001  (Docker network "web")
                         └──────────────────────────────────────────────────┘
```

Only Caddy publishes ports (80, 443). Services like Uptime Kuma publish **nothing**: they're reachable only
by name (`uptime-kuma`) inside the Docker network `web`. That also sidesteps the "Docker bypasses ufw"
pitfall from step 03 — there's nothing extra to bypass.

## 2. HTTPS in 60 seconds

HTTPS = HTTP inside an encrypted TLS connection. To prove it really is `diegoponte.dev`, the server shows a
**certificate** signed by a trusted **Certificate Authority** (CA).

**Let's Encrypt** is a free CA that issues certificates automatically through the **ACME** protocol:

1. Caddy asks: "I want a certificate for `diegoponte.dev`".
2. Let's Encrypt replies with a **challenge**: "prove you control it — serve this token at
   `http://diegoponte.dev/.well-known/acme-challenge/…`" (or over TLS on port 443).
3. Let's Encrypt fetches it **from the internet**. DNS points to our server (step 02), the firewalls allow
   80/443 (steps 01 and 03), Caddy answers → proven.
4. Certificate issued, valid for **90 days**. Caddy renews it automatically around 30 days before expiry.

That's why `.dev` (HTTPS-only, HSTS preload) didn't open before this step, and why DNS records were left
*DNS only* in step 02: Let's Encrypt must reach the server directly.

## 3. Walkthrough

### `stacks/caddy/conf/Caddyfile`

```caddy
{$DOMAIN} {
	import security_headers
	encode zstd gzip
	root * /srv/portfolio
	file_server
}
```

- Writing a hostname is all Caddy needs to enable HTTPS for it, including the HTTP → HTTPS redirect.
- `{$DOMAIN}` is replaced by an environment variable when the config loads, so the same file works for
  any domain (and for tests with `example.com`).
- `encode zstd gzip` compresses responses.
- `(security_headers)` is a **snippet** reused with `import`:
  - `Strict-Transport-Security` (HSTS): browsers remember to always use HTTPS for a year.
  - `X-Content-Type-Options: nosniff`: browsers don't guess file types (prevents some attacks).
  - `Referrer-Policy`: limits what URL is leaked to other sites when clicking a link.
  - `-Server`: removes the header that announces which server software is running.

```caddy
www.{$DOMAIN} {
	redir https://{$DOMAIN}{uri} permanent
}
```

One canonical address. `permanent` = HTTP 301, so search engines index only the apex.

```caddy
status.{$DOMAIN} {
	@outsiders not remote_ip {$ADMIN_CIDRS}
	respond @outsiders "Forbidden" 403
	reverse_proxy uptime-kuma:3001
}
```

`@outsiders` is a **named matcher**: requests *not* coming from `ADMIN_CIDRS` get `403`. Everything else is
proxied to the container.

> **Why lock the panel to your IP?** On first visit, Uptime Kuma lets *whoever arrives first* create the
> admin account. Certificates are published in public **Certificate Transparency** logs, and bots watch
> them to discover new subdomains within minutes. An open setup page would be claimed by a bot.

### `stacks/caddy/compose.yml`

- `ports: 80, 443` — the only published ports on the server.
- `./conf:/etc/caddy:ro` mounts a **directory**, not the single file. Tools that "edit" a file usually
  write a new file and rename it (new inode); a single-file bind mount keeps pointing to the old inode and
  the container never sees the change. Mounting the directory avoids that trap.
- `caddy_data` volume stores certificates and the ACME account. Losing it means re-issuing everything —
  and Let's Encrypt has rate limits. It's in the backup plan (step 06).
- `${DOMAIN:?…}` makes Compose fail loudly if the variable is missing, instead of starting with an empty value.

### `ansible/roles/stacks/`

1. Asserts `admin_cidrs` exists (it protects the panels).
2. Installs the Docker SDK for Python and creates the `web` network.
3. Copies `stacks/` to `/opt/stacks` and writes `caddy/.env` (`DOMAIN`, `ADMIN_CIDRS`).
4. `docker_compose_v2` starts each stack — idempotent: no change, no restart.
5. Handlers: a Caddyfile change triggers a **graceful reload** (`caddy reload`: zero downtime, open
   connections kept); an `.env` change **recreates** the container (environment is fixed at creation).

`admin_cidrs` has a single source of truth: `terraform.tfvars` → `terraform output admin_cidrs` →
generated inventory → Caddy. Changing your IP in one place updates both the SSH firewall and the panel.

## 4. Tests

**Before deploying** (`make test`, offline, also in CI):
- `docker compose config -q` validates every stack.
- `caddy validate` loads the Caddyfile with sample values and checks every directive.
- `make lint` also runs `caddy fmt --diff` (fails when the file isn't in canonical format).

**After deploying** (`make smoke`, against the real sites):

```
  ok    https://diegoponte.dev responds 200
  ok    http://diegoponte.dev redirects to HTTPS
  ok    www redirects to apex (301)
  ok    www redirect target
  ok    HSTS header present
  ok    Server header hidden
  ok    certificate valid (curl verifies TLS)
  ok    status panel reachable from admin IP
```

The `403` for outsiders was verified by calling `status.diegoponte.dev` from the server itself (its IP is
not in `admin_cidrs`).

## 5. Bugs found while doing this

The first deploy failed: `'NoneType' object is not iterable` while writing `caddy/.env`. The new Terraform
output `admin_cidrs` existed in the **code** but not yet in the **state** — outputs are only recorded on
`apply` — so the inventory got an empty value. Fixes: apply the output, and an `assert` at the top of the
role that fails with a clear message ("run `make plan && make apply`") instead of a cryptic error.

### …and a second one, only visible from a real browser

After the fix above, `make smoke` passed — but the browser still got **403**. The difference: Windows
connects over **IPv6** (the domain has AAAA records), while WSL only has IPv4.

Two problems stacked up:

1. `admin_cidrs` only had the IPv4 address. Fix: also allow the home IPv6 **/64** (the last 64 bits of a
   Windows IPv6 address rotate for privacy; the first 64 identify the network).
2. Even then, still 403. The Docker network `web` was **IPv4-only**, so Docker accepted IPv6 connections in
   a userland proxy (`docker-proxy -host-ip ::`) and forwarded them to Caddy over IPv4 — Caddy saw
   Docker's gateway `172.18.0.1` as `remote_ip`, never the visitor. Fix: create the network with
   `enable_ipv6: true` and a private IPv6 subnet (ULA, `fd4d:6f6e:6974::/64`); Docker then forwards IPv6
   natively with ip6tables and the source address is preserved.

How it was confirmed: the `status` site now has an access `log`, and a request over IPv6 shows the real
address (`"remote_ip":"2a01:…"`) instead of `172.18.0.1`.

Lesson: test from the client people will actually use. A check that only runs from one network
(here, IPv4-only WSL) can be green while real users fail.

## 6. Exercises

1. Inspect the certificate: `echo | openssl s_client -connect diegoponte.dev:443 -servername diegoponte.dev | openssl x509 -noout -issuer -dates`.
   When does it expire? When will Caddy renew it?
2. Search for `diegoponte.dev` on [crt.sh](https://crt.sh) — that's the Certificate Transparency log the bots read.
3. Add a header `Permissions-Policy "camera=(), microphone=()"` to the snippet, run `make lint`
   (did `caddy fmt` complain?), `make configure`, and check it with `curl -sI https://diegoponte.dev`.
4. Watch Caddy's logs during a deploy: `ssh deploy@diegoponte.dev 'cd /opt/stacks/caddy && docker compose logs -f'`.
5. Add a new subdomain `hello.diegoponte.dev` that answers `respond "hello"`: what needs to change in
   Terraform (DNS) and in the Caddyfile? Do it end to end.

## 7. Pitfalls

- **Let's Encrypt rate limits:** repeated failed attempts (wrong DNS, closed port) can block issuance for
  an hour; issuing many certificates for the same domain is limited per week. Get DNS and firewall right
  first; for experiments, Caddy can use the staging CA (`acme_ca https://acme-staging-v02.api.letsencrypt.org/directory`).
- **Your IP changed** → `status` returns 403 (and SSH times out). Update `admin_cidrs`, then
  `make plan && make apply && make configure`.
- **IPv6 at home:** if your browser connects over IPv6, your IPv4 in `admin_cidrs` won't match. Add your
  IPv6 /64 too (open https://ifconfig.me in the browser to see it). And any Docker network that receives
  public traffic needs IPv6 enabled, or visitor IPs are replaced by Docker's gateway (section 5).
- **Proxying (orange cloud) later:** with Cloudflare's proxy on, Caddy sees Cloudflare's IPs as
  `remote_ip`, which breaks the allowlist; you'd need `trusted_proxies` and `client_ip`.

## Further reading

- [Caddyfile concepts](https://caddyserver.com/docs/caddyfile/concepts)
- [Automatic HTTPS in Caddy](https://caddyserver.com/docs/automatic-https)
- [How Let's Encrypt works](https://letsencrypt.org/how-it-works/)
- [Certificate Transparency](https://certificate.transparency.dev/)
- [Docker Compose file reference](https://docs.docker.com/reference/compose-file/)
