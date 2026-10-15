# Automatic deploy (pull-based)

- **Date:** 2026-10-15
- **Status:** delivered (infra #11, portfolio #8 and #9)
- **ADRs:** —

## Goal

A merge to `main` in an app repo (first: `portfolio`) puts the new version live on the VPS within ~2
minutes, rolls back by itself if the new version is unhealthy, and the app's CI shows whether the deploy
worked. No inbound port is opened: SSH stays restricted to the admin IP.

## Out of scope

- Multi-server, blue/green or zero-downtime deploys (a static site restarts in ~1 s).
- Preview environments per PR.
- Deploying `infra` itself (still `make configure`, from the admin machine).

## Contracts

- **Image** (built by the app's CI): `ghcr.io/dpontejs/<app>:main` (moving tag) and `:sha-<commit>`;
  **public** package (the site is public content), so the VPS pulls without credentials.
- **Version endpoint** served by every app: `GET /version.json` → `{"commit": "<40-char sha>"}`,
  `Cache-Control: no-store`.
- **Image healthcheck** (`HEALTHCHECK` in the Dockerfile) hitting `/version.json`.
- **Stack** `stacks/<app>/compose.yml` on the `web` network; Caddy proxies `<host>` → `<app>:80`.
- **Agent** `stack-update <stack>` (Python, stdlib only) run every minute by `stack-update@<stack>.timer`
  as user `deploy`:
  1. `docker compose pull`; same image ID as running → exit 0 (nothing to do).
  2. pulled ID listed in `/var/lib/stack-update/<stack>.bad` → exit 0 (known broken).
  3. `docker compose up -d --wait --wait-timeout 90`; healthy → log `deployed`.
  4. unhealthy → retag the previous image ID, `up -d --wait` again, record the bad ID, exit 1.
- **Logs:** journald, `journalctl -u stack-update@portfolio`.
- Ansible: `auto_update_stacks: [portfolio]` enables one timer per stack.

## Acceptance criteria (as tests)

Agent (`tests/test_stack_update.py`, docker calls faked):
- [ ] `test_no_new_image_does_nothing`: given pulled ID == running ID, when run, then no `up` is called.
- [ ] `test_new_healthy_image_is_deployed`: given a new ID, when `up --wait` succeeds, then exit 0, no rollback.
- [ ] `test_unhealthy_image_rolls_back`: given `up --wait` fails, then the previous ID is retagged, `up` runs again, the new ID is recorded as bad, exit 1.
- [ ] `test_known_bad_image_is_skipped`: given the pulled ID is in the bad list, then no `up` is called.
- [ ] `test_first_deploy_without_running_container`: given nothing running, when a healthy image is pulled, then it is deployed.

Portfolio:
- [ ] e2e `version.json exposes the build commit`: given `GIT_SHA=abc…`, then `/version.json` returns it.
- [ ] CI `deploy` job: after pushing the image, polls `https://diegoponte.dev/version.json` until `commit == $GITHUB_SHA` (timeout 5 min) and fails otherwise.

## End-to-end verification

```bash
# merge a visible change in portfolio, then:
gh run watch                                    # CI: test → image → verify live = green
curl -s https://diegoponte.dev/version.json     # the merged commit
ssh deploy@diegoponte.dev journalctl -u stack-update@portfolio -n 20
# rollback drill: push an image whose healthcheck fails → previous version stays live, CI red
```

## Delivery (PRs, in order)

1. `portfolio`: Dockerfile, `version.json`, CI builds and pushes the image (no deploy yet).
2. `infra`: agent + tests, Ansible role, `portfolio` stack, Caddy proxies to it; placeholder page removed.
3. `portfolio`: CI `deploy` verification job.

## Risks and open questions

- A broken `main` image is rolled back but the site keeps the previous version until a fixed commit is
  merged — acceptable for a personal site.
- GHCR outage: the agent logs the pull error and retries next minute; the running version is untouched.
