# Resource monitoring (Beszel)

- **Date:** 2026-11-26
- **Status:** proposed
- **ADRs:** —

## Goal

See CPU, memory, disk and network for the VPS and for every container, with history, at
`https://monitor.<domain>` (admin IPs only), and get an e-mail when the machine runs out of headroom.
Uptime Kuma only says whether each site answers; sysstat keeps history, but only in a terminal.

## Out of scope

- Per-container disk I/O: Beszel 0.21.2 collects CPU, memory and network per container; disk usage
  and disk I/O are host-wide only.
- Stopped containers: Beszel only alerts on a running container that turns `unhealthy`
  (upstream henrygd/beszel#1786). Covered by the next PR (`container-watch` timer → Uptime Kuma push).
- Logs and APM. sysstat stays as it is.

## Contracts

- **Stack** `stacks/beszel/compose.yml`, pinned versions, not in `auto_update_stacks`:
  - `beszel` (`henrygd/beszel:0.21.2`): hub on the `web` network, port 8090 not published,
    data in the `beszel_data` volume (SQLite), `mem_limit: 192m`.
  - `beszel-agent` (`henrygd/beszel-agent:0.21.2`): `network_mode: host`; the hub reaches it
    through the unix socket `/beszel_socket/beszel.sock` (shared volume), so no TCP port is opened.
    `mem_limit: 64m`.
  - `docker-proxy` (`tecnativa/docker-socket-proxy:v0.5.0`): the only holder of `docker.sock`.
    A `:ro` socket mount still allows every API call; the proxy allows `GET /containers/*`,
    `/info` and `/version` only (POST, exec and images answer 403). Bound to `127.0.0.1:2375`.
    `mem_limit: 48m`.
- **Caddy:** `monitor.{$DOMAIN}` → `beszel:8090`, 403 outside `ADMIN_CIDRS` (same as `status.`).
- **DNS:** `monitor` in `var.subdomains` (A + AAAA, DNS only).
- **Secrets:** `BESZEL_AGENT_KEY` in `~/.config/infra/secrets.env` (the hub's public SSH key,
  shown in *Add System*). Until it is set, Ansible starts only the hub.
- **Alerts** (Beszel, per system, e-mail through Resend SMTP from `monitor@<domain>`):
  Disk > 85 %, Memory > 85 % for 5 min, CPU > 90 % for 10 min, ContainerHealth (unhealthy) for 1 min.
- **Uptime Kuma:** HTTP monitor on `http://beszel:8090/api/health` (internal, through `web`).

## Acceptance criteria (as tests)

- [x] `apex_and_subdomains_point_to_the_server` (terraform test): given the default subdomains,
  then `monitor.<domain>` gets a record.
- [x] `make stacks-test`: given sample values, the beszel compose and the Caddyfile validate.
- [x] Local run (Docker on the admin machine): hub + proxy + agent → system `up`, 31 containers with
  CPU/memory; the proxy log shows only GETs; `POST /containers/*/stop`, `/exec`, `/images` → 403.

## End-to-end verification

```bash
make check                       # dry run: only beszel files, its .env and the Caddyfile change
make configure                   # hub only; reloads Caddy (graceful)
curl -so /dev/null -w '%{http_code}\n' https://monitor.diegoponte.dev/   # 200 from an admin IP
# create the admin user, Add System (host /beszel_socket/beszel.sock), copy the key to
# BESZEL_AGENT_KEY, then:
make configure                   # starts the agent; system shows "up" with every container
```

## First install

1. `make plan && make apply` (DNS), then `make configure`: only the hub starts.
2. Open `https://monitor.<domain>`, create the admin user.
3. *Add System*: name `vps-01`, host `/beszel_socket/beszel.sock`; copy the public key into
   `BESZEL_AGENT_KEY` in `secrets.env`; `make configure` again.
4. Settings → SMTP (PocketBase, `/_/`): `smtp.resend.com:465`, user `resend`, the Resend API key.
   Then add the alerts above. Hub settings and alerts live in `beszel_data`, not in this repo.

## Cost on the VPS

Measured locally while idle: hub 14 MiB, agent 7 MiB, proxy 24 MiB, ~0 % CPU. The production numbers are
recorded below once the stack is running.

## Risks and open questions

- Hub data (`beszel_data`) is not backed up yet: losing it loses history and alert settings, not
  the stack (the shared backups feature on the roadmap will cover it).
