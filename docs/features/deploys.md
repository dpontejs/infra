# Status page: health, deploys and versions

- **Date:** 2026-11-27
- **Status:** in progress (slice 1: health + deploys; slice 2: versions)
- **ADRs:** —

## Goal

One screen at `https://deploys.<domain>` (admin IPs only) to open first: is the VPS fine, is every
service healthy, which version runs and did the latest one go live. Beszel stays for details.

## Out of scope

- History charts (Beszel) and alert rules (Beszel and Uptime Kuma keep sending them).
- pathoxp versions (GitLab); its containers do show up under health.
- E-mail on rollback (later: Kuma push, like `container-watch`).

## Contracts

All state lives in `/var/lib/status/` (owner `deploy`, files 0644), mounted read-only in the `deploys` stack.

**Slice 1: health and deploys**
- `container-watch` becomes Python (stdlib, like `stack-update`); every minute it still pushes up/down
  to Kuma, and also writes `health.json`:
  ```json
  {"generated_at": "…", "host": {"cpu_pct": 11.2, "load": [0.7, 0.4, 0.5], "mem_pct": 34, "swap_pct": 2, "disk_pct": 72, "uptime_s": 157000},
   "containers": [{"name": "today-today-1", "state": "running", "health": "healthy", "started_at": "…", "restarts": 0, "image": "ghcr.io/dpontejs/today:main"}],
   "sites": [{"name": "Beszel hub", "up": true}]}
  ```
  `cpu_pct` from `/proc/stat` since the previous run; `sites` from Uptime Kuma `/metrics`
  (`monitor_status`, read with an API key in `/etc/container-watch.env`); missing → `"sites": null`.
- `stack-update` writes `<stack>.json` on every run that pulls: `state` (`deploying` before
  `up --wait`, `deployed`, `rolled_back`, `skipped_bad`, `pull_failed`), `running` (`image_id`,
  `version`, `revision`, `source`, `since`) and `history` (last 20, newest first).
  `version`/`revision` come from image labels; until slice 2 they are null.
- Ansible writes `index.json`: `{"stacks": [<auto_update_stacks>]}`.
- **Page** `stacks/deploys/site/index.html` (static, no build), refreshes every 30 s: host bar
  (CPU, memory, disk; amber/red at the alert thresholds 85/90 %), one row per container (health,
  uptime, restarts, deploy state, version or short image id), sites, links to Beszel and Kuma.
- **Stack `deploys`:** a minimal `caddy:2.11.7` (port 8080, read-only, 32 MB) serves the page and
  `/var/lib/status` (read-only) at `/state/`. The main Caddy only gets `deploys.{$DOMAIN}` → `deploys:8080`,
  403 outside `ADMIN_CIDRS`: a graceful reload, no restart. **DNS:** `deploys` in `var.subdomains`.

**Slice 2: versions** (today, geral, hachibu, portfolio; separate PRs, after the dev's go)
- `semantic-release` on every merge to `main`, baseline tag `v0.1.0`, breaking → minor while 0.x.
- Dry run → build → smoke → push → release; labels `org.opencontainers.image.version`
  (`git describe`: `0.2.0` or `0.2.0+2`) and `.revision`; extra tag `:<version>` on releases.
- The page then links each version to `<source>/releases/tag/v<version>` and asks GitHub (one call per
  app, on load and every 10 min) for the CI run on `main`: building / failed / `head_sha` live or not.

## Acceptance criteria (as tests)

- [ ] `test_health_lists_running_stopped_and_missing`: given 3 watched containers (running+healthy,
  exited, absent), then `health.json` has `running/healthy`, `exited`, `missing`.
- [ ] `test_cpu_pct_from_previous_sample` and `test_first_run_has_no_cpu_pct` (null).
- [ ] `test_sites_from_kuma_metrics`; `test_kuma_unreachable_gives_null_sites_and_still_pushes`.
- [ ] Existing container-watch tests keep passing (push up/down, token out of argv).
- [ ] `test_state_deployed`, `test_state_deploying_before_wait`, `test_state_rolled_back`,
  `test_state_without_labels`, `test_history_keeps_last_20`.
- [ ] `deploys` in the DNS test; `make stacks-test` validates the Caddyfile and compose.

## End-to-end verification

```bash
make test && make check && make configure    # main Caddy: graceful reload only
curl -s https://deploys.diegoponte.dev/state/health.json | jq '.containers | length'   # 11
docker stop pathoxp-cloudflared-1  # NOT in prod: drill in a local stack → row turns red within 1 min
```

## Risks and open questions

- `/metrics` needs a Kuma API key (created through the Kuma API, stored in `secrets.env`).
