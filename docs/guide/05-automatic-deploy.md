# 05 — Automatic deploy: the server pulls new versions

> **Goal of this step:** a merge in an app repo goes live on its own within ~2 minutes, an unhealthy
> version is rolled back automatically, and nothing new is exposed to the internet.
>
> **Files:** [`agent/stack_update.py`](../../agent/stack_update.py) ·
> [`ansible/roles/deploy_agent/`](../../ansible/roles/deploy_agent) ·
> [`stacks/portfolio/`](../../stacks/portfolio) · design: [`docs/features/auto-deploy.md`](../features/auto-deploy.md)

## 1. Push or pull?

The textbook pipeline ends with CI connecting to the server over SSH and running `docker compose up`.
Here that collides with step 01: **SSH only accepts the admin's IP**, and GitHub's runners get a different
IP every run. Options considered:

| | How CI reaches the server | Cost |
|---|---|---|
| Open SSH to GitHub's IP ranges | thousands of CIDRs | exposes SSH to anything running on GitHub |
| Webhook (`deploy.diegoponte.dev`) | HTTPS + HMAC signature | a new internet-facing service with Docker access |
| Tailscale + SSH | private network, ephemeral node | new vendor and account |
| **Pull (chosen)** | **it doesn't: the server checks the registry** | ~1 min delay |

**Pull-based deploy** inverts the direction: CI only *publishes* an image; the server periodically asks
the registry "is there something new?". The server only makes **outgoing** requests — no port, no
credential for CI to hold. This is the idea behind GitOps tools such as Argo CD and Flux, at the size of
one VPS.

```
merge → CI: tests → image → ghcr.io/dpontejs/portfolio:main
                                        ▲
         VPS: stack-update@portfolio.timer (every minute)
              pull → new? → up --wait → healthy? ✓ deployed
                                       └─ ✗ roll back + remember the bad image
```

## 2. The agent, step by step

`stack-update portfolio` (Python, standard library only — it runs with the server's own Python):

1. **Preserve** the running image with a local tag `:rollback` (why *before* pulling: section 4).
2. **Pull** `:main`. Same image ID as the running container → nothing to do (the usual case: exit 0).
3. Image ID in `/var/lib/stack-update/portfolio.bad` → skip it. Without this, a broken image would be
   deployed and rolled back every single minute.
4. `docker compose up --detach --wait`: `--wait` blocks until the container's **healthcheck** reports
   `healthy` (the image defines it: `wget /version.json`) or fails.
5. Unhealthy → retag the preserved image as `:main`, `up --force-recreate`, record the bad ID, exit 1.

It's split in two layers so the logic is testable without Docker:
- `update(stack, docker, state_dir)` — **decisions** only, talking to a `DockerLike` interface;
- `Docker` — a thin wrapper that turns those calls into `docker` CLI commands.

## 3. systemd: timer + template unit

`stack-update@.service` is a **template**: `stack-update@portfolio.service` runs it with `%i = portfolio`.
A matching `stack-update@portfolio.timer` starts it every minute (`OnUnitActiveSec=1min`).

- `Type=oneshot`: runs and exits; the timer schedules the next run.
- `User=deploy`: no root; the `docker` group is enough.
- `StateDirectory=stack-update`: systemd creates `/var/lib/stack-update` owned by `deploy`.
- Logs go to the journal: `journalctl -u stack-update@portfolio -f`.

Adding another auto-deployed app = a new stack folder + its name in `auto_update_stacks`.

## 4. Two bugs only a real Docker could show

The unit tests (`agent/test_stack_update.py`) fake Docker in memory and passed from the start. The
**integration test** (`agent/integration_stack_update.py`) runs a local registry, publishes a healthy v1,
a healthy v2 and a **broken v3**, and checks deploy → upgrade → no-op → rollback → skip. It failed twice:

1. **Compose kept the broken container after the retag.** For registry images, Compose compares repo
   digests, not just the local tag, so `up` saw "nothing changed". Fix: `--force-recreate` on rollback.
2. **The previous image no longer existed.** Docker 29 stores images in **containerd**, where an image
   exists only while a tag points to it. Once `pull` moved `:main`, v2 disappeared — even with its container
   still running — and `docker tag` failed with *No such image* (silently: the first version ignored the exit
   code). Fix: tag the running image `:rollback` **before** pulling, and treat a failed `tag` as an error.

Both are now encoded in the fake used by the unit tests (an image exists only while tagged; rollback must
force a recreate), so the fast suite catches a regression too. Lesson: a fake is only as good as your
model of the real system — an integration test is what corrects the model.

## 5. How CI knows the deploy worked

The app's CI can't see the server, but it can see the **site**. After pushing the image, the portfolio
workflow polls `https://diegoponte.dev/version.json` until it shows the merged commit (timeout 5 min).
Rolled back or stuck → the commit never appears → CI turns red. `version.json` is `no-store`, so no cache
lies to it.

## 6. Exercises

1. Watch a deploy live: `ssh deploy@diegoponte.dev journalctl -u stack-update@portfolio -f`, then merge
   a change in the portfolio.
2. `systemctl list-timers 'stack-update@*'` — when is the next run?
3. Run `make test-integration` and read the test while it runs: which assertion covers each bug in section 4?
4. Rollback drill: in a portfolio branch, break the healthcheck (`/nope.json`), push the image manually
   with the `:main` tag, and watch the agent roll back. Then check `/var/lib/stack-update/portfolio.bad`.
5. Why does the agent exit 0 when it skips a known bad image, but 1 when it rolls back?

## 7. Pitfalls

- **The registry package must be public** (or the server needs a token): otherwise `pull` fails every minute.
- **`make configure` runs `docker compose up` too.** After a rollback, `:main` locally points to the broken
  image again on the next pull; a `make configure` at that moment would start it. Fix the app first.
- **Clock-based, not event-based:** up to a minute passes before the server notices a new image.

## Further reading

- [systemd timers](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
- [docker compose up `--wait`](https://docs.docker.com/reference/cli/docker/compose/up/)
- [Docker containerd image store](https://docs.docker.com/engine/storage/containerd/)
- [GitOps principles](https://opengitops.dev/)
