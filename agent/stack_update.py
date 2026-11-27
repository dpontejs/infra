#!/usr/bin/env python3
"""stack-update: pull-based deploy for one Docker Compose stack.

Run every minute by `stack-update@<stack>.timer` (see docs/features/auto-deploy.md):

1. pull the stack's image; same image as the running container -> nothing to do;
2. image already known to be broken -> skip it;
3. start it and wait for the container healthcheck;
4. unhealthy -> put the previous image back, remember the broken one, exit 1.

With --status-dir, every run also writes <status-dir>/<stack>.json for the deploys page
(docs/features/deploys.md): deploy state, the running image's version labels and the last attempts.

Standard library only: it runs with the server's system Python.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol, Sequence

log = logging.getLogger("stack-update")

HEALTH_TIMEOUT_SECONDS = 90
HISTORY_LENGTH = 20
LABEL_PREFIX = "org.opencontainers.image."


class DockerLike(Protocol):
    def image_ref(self) -> str: ...
    def running_image_id(self) -> str | None: ...
    def pull(self) -> bool: ...
    def local_image_id(self, ref: str) -> str | None: ...
    def up_wait(self, timeout: int, force_recreate: bool = False) -> bool: ...
    def tag(self, image_id: str, ref: str) -> bool: ...
    def image_labels(self, image_id: str) -> dict[str, str]: ...


def rollback_ref(ref: str) -> str:
    """'ghcr.io/me/app:main' -> 'ghcr.io/me/app:rollback' (a tag that only exists on this server)."""
    name, _, tag = ref.rpartition(":")
    repository = name if name and "/" not in tag else ref
    return f"{repository}:rollback"


class Status:
    """<status_dir>/<stack>.json: what the deploys page shows. A no-op without a status dir."""

    def __init__(self, status_dir: Path | None, stack: str, docker: DockerLike) -> None:
        self.path = status_dir / f"{stack}.json" if status_dir else None
        self.docker = docker
        self.data: dict = {"stack": stack, "state": None, "running": None, "history": []}
        if self.path and self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except (OSError, ValueError):
                log.warning("unreadable status file %s; starting a new one", self.path)

    def image(self, image_id: str | None, since: str | None = None) -> dict | None:
        if image_id is None:
            return None
        labels = self.docker.image_labels(image_id) or {}
        return {
            "image_id": image_id,
            "version": labels.get(LABEL_PREFIX + "version"),
            "revision": labels.get(LABEL_PREFIX + "revision"),
            "source": labels.get(LABEL_PREFIX + "source"),
            "since": since,
        }

    def write(
        self,
        state: str,
        running: str | None,
        target: str | None = None,
        result: str | None = None,
        attempted: str | None = None,
    ) -> None:
        """target: image waiting to go live (deploying, skipped). result + attempted: a history entry."""
        if self.path is None:
            return
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        previous = self.data.get("running") or {}
        if running is not None and previous.get("image_id") == running:
            self.data["running"] = {**self.image(running), "since": previous.get("since")}
        else:
            # A new image is running since now; an unknown one (first run with a status dir) since when
            # nobody knows.
            self.data["running"] = self.image(running, since=now if result == "deployed" else None)
        self.data["target"] = self.image(target)
        self.data["state"] = state
        self.data["checked_at"] = now
        if result is not None:
            entry = {**(self.image(attempted) or {}), "at": now, "result": result}
            entry.pop("since", None)
            self.data["history"] = [entry, *self.data.get("history", [])][:HISTORY_LENGTH]
        # Atomic: the page never reads a half-written file.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.chmod(tmp, 0o644)
        tmp.replace(self.path)


def update(
    stack: str,
    docker: DockerLike,
    state_dir: Path,
    timeout: int = HEALTH_TIMEOUT_SECONDS,
    status_dir: Path | None = None,
) -> int:
    """Deploys a new image for `stack` if there is one. Returns the process exit code."""
    status = Status(status_dir, stack, docker)
    ref = docker.image_ref()
    running = docker.running_image_id()

    # Preserve the running image BEFORE pulling. With Docker's containerd image store an image only
    # exists while a tag points to it: once `pull` moves :main away, the old image can't be tagged
    # again, even while a container runs it (found by agent/integration_stack_update.py).
    if running and not docker.tag(running, rollback_ref(ref)):
        log.warning("could not preserve %s for rollback", running)

    if not docker.pull():
        log.error("pull of %s failed; keeping the running version", ref)
        status.write("pull_failed", running)
        return 1
    pulled = docker.local_image_id(ref)
    if pulled is None:
        log.error("%s not found locally after pull", ref)
        status.write("pull_failed", running)
        return 1
    if pulled == running:
        status.write("deployed", running)
        return 0

    bad_file = state_dir / f"{stack}.bad"
    bad = bad_file.read_text().split() if bad_file.exists() else []
    if pulled in bad:
        log.info("skipping %s: known to be unhealthy", pulled)
        status.write("skipped_bad", running, target=pulled)
        return 0

    log.info("deploying %s (%s), replacing %s", ref, pulled, running or "nothing")
    status.write("deploying", running, target=pulled)
    if docker.up_wait(timeout):
        log.info("deployed %s", pulled)
        status.write("deployed", pulled, result="deployed", attempted=pulled)
        return 0

    log.error("%s is unhealthy", pulled)
    now_running: str | None = pulled
    result = "failed"
    if running:
        # Point the tag back at the previous image (kept alive by the :rollback tag) and force the
        # recreate: for registry images, compose compares repo digests and would otherwise keep the
        # unhealthy container running (both found by agent/integration_stack_update.py).
        if not docker.tag(running, ref):
            log.critical("cannot roll back: previous image %s no longer exists", running)
        elif docker.up_wait(timeout, force_recreate=True):
            log.warning("rolled back to %s", running)
            now_running, result = running, "rolled_back"
        else:
            log.critical("rollback to %s is unhealthy too", running)
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_text("".join(f"{image}\n" for image in [*bad, pulled]))
    status.write(result, now_running, result=result, attempted=pulled)
    return 1


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


class Docker:
    """Thin wrapper over the docker CLI for one compose service."""

    def __init__(self, directory: Path, service: str, runner: Runner = run) -> None:
        self.directory = directory
        self.service = service
        self.runner = runner

    def _compose(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = self.runner(["docker", "compose", "--project-directory", str(self.directory), *args])
        if result.returncode != 0:
            log.debug("docker compose %s: %s", " ".join(args), result.stderr.strip())
        return result

    def image_ref(self) -> str:
        config = json.loads(self._compose("config", "--format", "json").stdout)
        return str(config["services"][self.service]["image"])

    def running_image_id(self) -> str | None:
        container = self._compose("ps", "--quiet", self.service).stdout.strip()
        if not container:
            return None
        result = self.runner(["docker", "inspect", "--format", "{{.Image}}", container])
        return result.stdout.strip() or None

    def pull(self) -> bool:
        return self._compose("pull", "--quiet", self.service).returncode == 0

    def local_image_id(self, ref: str) -> str | None:
        result = self.runner(["docker", "image", "inspect", "--format", "{{.Id}}", ref])
        return result.stdout.strip() if result.returncode == 0 else None

    def up_wait(self, timeout: int, force_recreate: bool = False) -> bool:
        flags = ["--force-recreate"] if force_recreate else []
        result = self._compose(
            "up", "--detach", *flags, "--wait", "--wait-timeout", str(timeout), self.service
        )
        return result.returncode == 0

    def image_labels(self, image_id: str) -> dict[str, str]:
        result = self.runner(["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", image_id])
        try:
            return json.loads(result.stdout) or {} if result.returncode == 0 else {}
        except ValueError:
            return {}

    def tag(self, image_id: str, ref: str) -> bool:
        result = self.runner(["docker", "tag", image_id, ref])
        if result.returncode != 0:
            log.debug("docker tag %s %s: %s", image_id, ref, result.stderr.strip())
        return result.returncode == 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stack", help="stack name, e.g. portfolio")
    parser.add_argument("--stacks-dir", type=Path, default=Path("/opt/stacks"))
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/stack-update"))
    parser.add_argument("--service", help="compose service (default: same as the stack)")
    parser.add_argument("--status-dir", type=Path, help="write <status-dir>/<stack>.json for the deploys page")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    docker = Docker(args.stacks_dir / args.stack, args.service or args.stack)
    return update(args.stack, docker, args.state_dir, status_dir=args.status_dir)


if __name__ == "__main__":
    sys.exit(main())
