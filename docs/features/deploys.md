# Versioned images and a deploys page

- **Date:** 2026-11-27
- **Status:** proposed
- **ADRs:** —

## Goal

Every app image carries a semantic version and its commit, and `https://deploys.<domain>` (admin IPs
only) shows, per app: the version running, whether the latest one is live, still deploying or was
rolled back, and the recent deploys, each linking to the GitHub release with the commits it contains.

## Out of scope

- E-mail on rollback (next step: push to Uptime Kuma like `container-watch`).
- pathoxp (GitLab, deployed outside this repo) and edutoria (stopped).
- Pinning versions in the compose files: the VPS keeps following `:main`.

## Contracts

**Apps** (today, geral, flamengo-news, hachibu, portfolio), `image` job of `ci.yml`, on `main` only:
- `semantic-release` (pinned) with `@semantic-release/commit-analyzer`, `release-notes-generator`,
  `github` and `exec`. `.releaserc.json`: branch `main`, preset `conventionalcommits`,
  `releaseRules: [{"breaking": true, "release": "minor"}]` (0.x: a breaking change bumps the minor;
  1.0.0 is a manual `v1.0.0` tag). Tag format `v${version}`. Release notes titled in Portuguese.
- Baseline: tag `v0.1.0` on the commit running today, pushed once per repo.
- Order: `semantic-release --dry-run` (exec writes the next version) → build → smoke → push → real
  release. A broken image never gets a release.
- Version label: `git describe --tags --match 'v*'` → `0.2.0` on a release commit, `0.2.0+2` two
  commits after it (`fetch-depth: 0`). Image labels: `org.opencontainers.image.version`,
  `org.opencontainers.image.revision` (`$GITHUB_SHA`), `org.opencontainers.image.created`.
- Tags pushed: `:main`, `:sha-<commit>` as today, plus `:<version>` on release commits.
- `concurrency: release-main` (no cancel) so two merges never compute the same version.

**Agent** `stack-update` writes `/var/lib/stack-update/<stack>.json` (0644) on every run that pulls:
```json
{"stack": "today", "state": "deployed", "checked_at": "2026-11-27T10:00:00-03:00",
 "running": {"image_id": "sha256:…", "version": "0.2.0", "revision": "<sha>", "source": "https://github.com/dpontejs/today", "since": "…"},
 "history": [{"at": "…", "image_id": "sha256:…", "version": "0.2.0", "revision": "<sha>", "result": "deployed"}]}
```
- `state`: `deploying` (written before `up --wait`), `deployed`, `rolled_back`, `skipped_bad`,
  `pull_failed`. `history`: last 20 attempts, newest first. Labels missing → `version: null`.
- Ansible writes `/var/lib/stack-update/index.json`: `{"stacks": [<auto_update_stacks>]}`.

**Page** `stacks/caddy/deploys/index.html` (static HTML + JS, no build): reads `/state/index.json` and
each `/state/<stack>.json` (every 30 s). Release links need no API: `<source>/releases/tag/v<version>`.
From the browser, one GitHub API call per app (public repos, 60 req/h per visitor IP):
`GET /repos/dpontejs/<app>/actions/runs?branch=main&event=push&per_page=1` → CI status (queued /
in progress / failed) and `head_sha`; `head_sha == running.revision` means the latest is live. Asked
on load, every 10 min (30 req/h) and from an "atualizar GitHub" button.
- **Caddy:** `deploys.{$DOMAIN}`, 403 outside `ADMIN_CIDRS`, `file_server` over
  `/srv/deploys` (page) and `/srv/deploys/state` (`/var/lib/stack-update`, read-only bind mount).
- **DNS:** `deploys` in `var.subdomains`.

## Acceptance criteria (as tests)

- [ ] `test_state_written_on_healthy_deploy`: given a new image with labels, when deployed, then the
  JSON has `state=deployed`, `running.version` from the label and a `deployed` entry in `history`.
- [ ] `test_state_deploying_before_wait`: given `up_wait` in progress, then the file says `deploying`.
- [ ] `test_state_rolled_back`: given an unhealthy image, then `state=rolled_back`, `running` is the
  previous image and `history[0].result=rolled_back`.
- [ ] `test_state_without_labels`: given an image without labels, then `version` is null, no crash.
- [ ] `test_history_keeps_last_20`; `test_no_new_image_only_updates_checked_at`.
- [ ] `apex_and_subdomains_point_to_the_server` covers `deploys`; `make stacks-test` validates Caddy.
- [ ] Per app: a merge with `feat:` creates `v0.2.0`, a release listing its commits and image `:0.2.0`
  with both labels; a `docs:` merge creates no release and deploys `0.2.0+1`.

## End-to-end verification

```bash
make test && make check && make configure    # recreates Caddy once (new mount): ~2 s
# merge a feat: in today → CI green, release v0.2.0 on GitHub, then:
curl -s https://deploys.diegoponte.dev/state/today.json   # running.version == "0.2.0"
```

## Risks and open questions

- Caddy is recreated once to add the bind mount (all sites ~2 s down), needs the dev's OK.
- Two open tabs share the 60 req/h limit (2 × 30): fine for one admin; a third tab would hit it
  and the page shows "limite do GitHub" until the hour resets. The state files are unaffected.
