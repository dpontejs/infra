# 03 — Hardening and configuring the server with Ansible

> **Goal of this step:** turn a fresh Ubuntu server into a safe, ready-to-use Docker host — from code,
> repeatably — and stop logging in as `root`.
>
> **Files:** [`ansible/`](../../ansible) · **Issue:** #2

## 1. Terraform vs. Ansible

| | Terraform (steps 01–02) | Ansible (this step) |
|---|---|---|
| Works on | the **cloud API** | **inside** the server, over SSH |
| Creates | servers, firewalls, DNS records | users, packages, config files, services |
| Remembers | a state file | nothing — it checks the server every run |

Terraform builds the house; Ansible furnishes it and changes the locks.

## 2. Core concepts

| Concept | In plain words | Where |
|---|---|---|
| **Inventory** | The list of servers to manage | `ansible/inventory.yml` (generated from Terraform) |
| **Playbook** | Which roles run on which hosts | `ansible/playbook.yml` |
| **Role** | A reusable bundle of tasks for one concern | `ansible/roles/<name>/` |
| **Task** | One action using a **module** (`apt`, `user`, `template`…) | `roles/*/tasks/main.yml` |
| **Handler** | A task that runs only when notified, once, at the end | `roles/*/handlers/main.yml` |
| **Template** | A config file with variables (Jinja2) | `roles/*/templates/*.j2` |
| **Variables** | Values shared by all roles | `ansible/group_vars/all.yml` |

### Idempotency — the most important idea

Every module first checks the current state and acts **only if needed**. Running the playbook twice must
produce `changed=0` the second time. That's what makes it safe to re-run anytime — and it was verified
on the real server:

```
vps-01 : ok=29  changed=0  unreachable=0  failed=0
```

When a task can't be idempotent by itself (a raw shell command), we make it so: the swap task uses
`creates: /swapfile`, so it's skipped once the file exists.

## 3. What each role does

The playbook runs the roles in this order. `ssh` is **last on purpose** (see 3.7).

### 3.1 `base` — updates and housekeeping
- Upgrades all packages and installs basic tools.
- Sets the timezone to `America/Fortaleza`.
- Enables **unattended-upgrades**: security patches install daily on their own. If a patch needs a reboot
  (e.g. a new kernel), the server reboots at **04:30**; containers come back thanks to their restart policy.

### 3.2 `users` — a non-root user
- Creates `deploy` with a **locked password** (`password: "!"`): it can only log in with an SSH key.
- Installs your public key (`exclusive: true` removes any key that isn't in the code).
- Grants `sudo` without password, so automation can run admin tasks. The sudoers file is checked with
  `visudo -cf` before being installed — a broken sudoers file could lock you out of `sudo` entirely.

> **Why not keep using root?** Root can do anything, so a stolen root session is game over, and every
> bot on the internet tries `root` first. With `deploy` + sudo, you must know the username *and* have the
> key, and admin actions are explicit and logged.

### 3.3 `firewall` — ufw, the second layer
`ufw` (Uncomplicated Firewall) filters traffic **inside** the server:
- deny everything incoming by default;
- `80`/`443` allowed;
- `22` with **`limit`**: an IP opening 6+ connections in 30 seconds gets blocked temporarily.

Why two firewalls (Hetzner + ufw)? **Defense in depth**: if one is misconfigured, the other still protects.

### 3.4 `fail2ban` — banning brute force
fail2ban reads the SSH logs (via systemd's journal) and bans IPs with **5 failures in 10 minutes** for
**1 hour**. Check it with:

```bash
sudo fail2ban-client status sshd
```

### 3.5 `swap` — a safety cushion for memory
A 2 GB file on disk used when RAM runs out, so a memory spike slows things down instead of the kernel
killing processes. `vm.swappiness = 10` tells Linux to prefer RAM and use swap only when needed.

### 3.6 `docker` — the container runtime
- Installs Docker Engine + Compose from **Docker's official repository** (Ubuntu's packages lag behind).
  The repository is signed: apt only accepts packages signed with Docker's GPG key.
- `daemon.json`: log rotation (3 × 10 MB per container — without it, logs can fill the disk) and
  `live-restore` (containers keep running while the Docker daemon restarts/upgrades).
- Adds `deploy` to the `docker` group.
- A **systemd timer** prunes unused images/containers older than 7 days, every Sunday at 05:00.
  Volumes are never pruned — they hold data.

> ⚠️ Being in the `docker` group is **equivalent to root**: whoever can run containers can mount the
> host's disk. Only trusted users belong there.

### 3.7 `ssh` — locking the door (last)
Installs `/etc/ssh/sshd_config.d/10-hardening.conf`:

```
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers deploy
MaxAuthTries 3
```

Three safety nets prevent locking yourself out:
1. **An assertion** fails the play if `deploy` has no `authorized_keys`.
2. **`validate: sshd -t -f %s`** tests the new file before installing it; a syntax error never reaches the server.
3. **The restart is a handler**, so it happens at the very end, after everything else succeeded.

Why `10-`? sshd reads `sshd_config.d/*.conf` in alphabetical order and **the first value wins**. Ubuntu
ships `50-cloud-init.conf` with `PasswordAuthentication yes`; our `10-` file is read first, so it wins.

## 4. Bootstrap vs. configure

There's a chicken-and-egg problem: the first run must connect as **root** (`deploy` doesn't exist yet),
but the run itself disables root login. So there are two commands:

```bash
make bootstrap   # first run only: connects as root, ends by disabling root login
make configure   # every run after: connects as deploy
make check       # dry run: shows what would change (--check --diff), changes nothing
```

The inventory is generated from `terraform output` (`make inventory`), so the server IP has a single
source of truth.

## 5. A real bug found while doing this

The first bootstrap failed at the SSH step:

```
failed to validate: Missing privilege separation directory: /run/sshd
```

Ubuntu 24.04 starts sshd **on demand** (systemd *socket activation*): the `/run/sshd` directory only
exists while sshd is running, and `sshd -t` refuses to validate without it. The fix is a task that
creates the directory before validating.

Notice how the safety nets worked: validation failed, so the new config was **not** installed, the
handler never ran, and access was untouched. Fix, re-run, done.

## 6. Verifying

```bash
ssh -i ~/.ssh/hetzner_vps root@diegoponte.dev     # → Permission denied (publickey)
ssh -i ~/.ssh/hetzner_vps deploy@diegoponte.dev   # → works
sudo sshd -T | grep -E 'permitrootlogin|passwordauthentication'
sudo ufw status
swapon --show
docker run --rm hello-world
systemctl list-timers docker-prune.timer
```

## 7. Exercises

1. Run `make configure` twice and confirm `changed=0`. Then edit `swap_swappiness` to `20`, run
   `make check` and read the diff before applying.
2. From your machine, try `ssh root@diegoponte.dev` a few times and watch
   `sudo fail2ban-client status sshd` on the server. (Careful: 5 failures ban **your** IP for 1 hour —
   unban with `sudo fail2ban-client set sshd unbanip <ip>` from the Hetzner web console.)
3. Read `/etc/ssh/sshd_config.d/` on the server and find the `50-cloud-init.conf` setting we override.
4. Run `docker run -d -p 8080:80 nginx` and try `curl http://diegoponte.dev:8080` from your machine.
   It times out — which firewall blocked it? (Hint: read the pitfall below about Docker and ufw.)
   Clean up with `docker rm -f $(docker ps -q)`.
5. Add a role `motd` that shows a custom login message, and run `make configure`.

## 8. Pitfalls

- **Docker bypasses ufw.** Ports published with `-p` are opened by Docker directly in iptables, *before*
  ufw's rules. In exercise 4, what blocked port 8080 was the **Hetzner cloud firewall**, not ufw. That's
  why we keep both layers, and why services will only be exposed through Caddy on 80/443 (step 04).
- **Your IP changed and SSH times out?** It's the Hetzner firewall (step 01): update `admin_cidrs`, then
  `make plan && make apply`.
- **Lost the SSH key** = lost access. Keep a backup of `~/.ssh/hetzner_vps` (password manager) — the
  Hetzner web console is the emergency door.
- **Ansible needs a UTF-8 locale.** The Makefile sets `LC_ALL=C.UTF-8`; on WSL you can also generate yours
  with `sudo locale-gen en_US.UTF-8`.

## Further reading

- [Ansible: Getting started](https://docs.ansible.com/ansible/latest/getting_started/index.html)
- [Ansible roles](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_reuse_roles.html)
- [sshd_config manual](https://man.openbsd.org/sshd_config)
- [Docker and ufw](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Unattended upgrades (Ubuntu)](https://ubuntu.com/server/docs/how-to/software/automatic-updates/)
