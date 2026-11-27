"""Tests for stack_update.update(): the deploy decision logic, with Docker faked in memory."""

import tempfile
import unittest
from pathlib import Path

import json

from stack_update import rollback_ref, update

REF = "ghcr.io/dpontejs/portfolio:main"
ROLLBACK = "ghcr.io/dpontejs/portfolio:rollback"


class FakeDocker:
    """In-memory stand-in for the Docker CLI wrapper: records every action.

    Mimics Docker 29's containerd image store: an image exists only while some tag points to it.
    Once `pull` moves the tag away, the old image can't be tagged again, even if a container still
    runs it (found by agent/integration_stack_update.py).
    """

    def __init__(self, running, remote, healthy=True, pull_ok=True, labels=None):
        self.labels = labels or {}  # image ID -> OCI labels (only read when a status dir is given)
        self.running = running  # image ID of the running container (None = nothing running)
        self.remote = remote  # image ID that `pull` will bring for REF
        self.healthy = healthy  # whether `up --wait` reports healthy
        self.pull_ok = pull_ok
        self.tags = {REF: running} if running else {}
        self.actions = []

    def _exists(self, image_id):
        return image_id in self.tags.values()

    def image_ref(self):
        return REF

    def running_image_id(self):
        return self.running

    def pull(self):
        self.actions.append("pull")
        if self.pull_ok:
            self.tags[REF] = self.remote
        return self.pull_ok

    def local_image_id(self, ref):
        return self.tags.get(ref)

    def up_wait(self, timeout, force_recreate=False):
        image = self.tags[REF]
        self.actions.append(f"{'recreate' if force_recreate else 'up'}:{image}")
        # The old container is replaced even when the new one turns out unhealthy.
        self.running = image
        return self.healthy or image != self.remote

    def image_labels(self, image_id):
        return self.labels.get(image_id, {})

    def tag(self, image_id, ref):
        if not self._exists(image_id):
            self.actions.append(f"tag-failed:{image_id}")
            return False
        self.actions.append(f"tag:{image_id}->{ref.rsplit(':', 1)[1]}")
        self.tags[ref] = image_id
        return True


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp())

    def bad_list(self):
        path = self.state / "portfolio.bad"
        return path.read_text().split() if path.exists() else []

    def test_no_new_image_does_nothing(self):
        docker = FakeDocker(running="sha256:aaa", remote="sha256:aaa")
        self.assertEqual(update("portfolio", docker, self.state), 0)
        self.assertEqual(docker.actions, ["tag:sha256:aaa->rollback", "pull"])

    def test_new_healthy_image_is_deployed(self):
        docker = FakeDocker(running="sha256:aaa", remote="sha256:bbb")
        self.assertEqual(update("portfolio", docker, self.state), 0)
        self.assertEqual(docker.actions, ["tag:sha256:aaa->rollback", "pull", "up:sha256:bbb"])
        self.assertEqual(docker.running, "sha256:bbb")
        self.assertEqual(self.bad_list(), [])

    def test_unhealthy_image_rolls_back(self):
        docker = FakeDocker(running="sha256:aaa", remote="sha256:bad", healthy=False)
        self.assertEqual(update("portfolio", docker, self.state), 1)
        self.assertEqual(
            docker.actions,
            [
                "tag:sha256:aaa->rollback",
                "pull",
                "up:sha256:bad",
                "tag:sha256:aaa->main",
                "recreate:sha256:aaa",
            ],
        )
        self.assertEqual(docker.running, "sha256:aaa")
        self.assertEqual(self.bad_list(), ["sha256:bad"])

    def test_known_bad_image_is_skipped(self):
        (self.state / "portfolio.bad").write_text("sha256:bad\n")
        docker = FakeDocker(running="sha256:aaa", remote="sha256:bad")
        self.assertEqual(update("portfolio", docker, self.state), 0)
        self.assertEqual(docker.actions, ["tag:sha256:aaa->rollback", "pull"])

    def test_first_deploy_without_running_container(self):
        docker = FakeDocker(running=None, remote="sha256:bbb")
        self.assertEqual(update("portfolio", docker, self.state), 0)
        self.assertEqual(docker.actions, ["pull", "up:sha256:bbb"])

    def test_unhealthy_first_deploy_has_nothing_to_roll_back(self):
        docker = FakeDocker(running=None, remote="sha256:bad", healthy=False)
        self.assertEqual(update("portfolio", docker, self.state), 1)
        self.assertEqual(docker.actions, ["pull", "up:sha256:bad"])
        self.assertEqual(self.bad_list(), ["sha256:bad"])

    def test_pull_failure_keeps_running_version(self):
        docker = FakeDocker(running="sha256:aaa", remote="sha256:bbb", pull_ok=False)
        self.assertEqual(update("portfolio", docker, self.state), 1)
        self.assertEqual(docker.actions, ["tag:sha256:aaa->rollback", "pull"])
        self.assertEqual(docker.running, "sha256:aaa")

    def test_rollback_fails_loudly_when_previous_image_is_gone(self):
        docker = FakeDocker(running="sha256:aaa", remote="sha256:bad", healthy=False)
        docker.tags = {}  # the running image lost its tag before we could preserve it
        self.assertEqual(update("portfolio", docker, self.state), 1)
        self.assertEqual(docker.actions.count("tag-failed:sha256:aaa"), 2)  # preserve + rollback
        self.assertNotIn("recreate:sha256:aaa", docker.actions)
        self.assertEqual(self.bad_list(), ["sha256:bad"])

    def test_rollback_ref_keeps_repository_and_port(self):
        self.assertEqual(rollback_ref(REF), ROLLBACK)
        self.assertEqual(rollback_ref("127.0.0.1:5055/app:main"), "127.0.0.1:5055/app:rollback")
        self.assertEqual(rollback_ref("busybox"), "busybox:rollback")

    def test_bad_list_keeps_previous_entries(self):
        (self.state / "portfolio.bad").write_text("sha256:old\n")
        docker = FakeDocker(running="sha256:aaa", remote="sha256:bad", healthy=False)
        update("portfolio", docker, self.state)
        self.assertEqual(self.bad_list(), ["sha256:old", "sha256:bad"])


if __name__ == "__main__":
    unittest.main()


SOURCE = "https://github.com/dpontejs/portfolio"


def labels(version, revision):
    return {
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.revision": revision,
        "org.opencontainers.image.source": SOURCE,
    }


class StatusTest(unittest.TestCase):
    """The status file (<status_dir>/<stack>.json) read by the deploys page."""

    def setUp(self):
        self.state = Path(tempfile.mkdtemp())
        self.status_dir = Path(tempfile.mkdtemp())

    def run_update(self, docker):
        return update("portfolio", docker, self.state, timeout=1, status_dir=self.status_dir)

    def status(self):
        return json.loads((self.status_dir / "portfolio.json").read_text())

    def test_state_deployed(self):
        docker = FakeDocker("sha256:old", "sha256:new", labels={"sha256:new": labels("0.2.0", "abc")})
        self.assertEqual(self.run_update(docker), 0)
        status = self.status()
        self.assertEqual(status["state"], "deployed")
        self.assertEqual(status["running"]["image_id"], "sha256:new")
        self.assertEqual(status["running"]["version"], "0.2.0")
        self.assertEqual(status["running"]["revision"], "abc")
        self.assertEqual(status["running"]["source"], SOURCE)
        self.assertEqual(status["history"][0]["result"], "deployed")
        self.assertEqual(status["history"][0]["version"], "0.2.0")

    def test_state_deploying_before_wait(self):
        seen = {}
        docker = FakeDocker("sha256:old", "sha256:new")
        original = docker.up_wait

        def up_wait(timeout, force_recreate=False):
            seen.update(self.status())
            return original(timeout, force_recreate)

        docker.up_wait = up_wait
        self.run_update(docker)
        self.assertEqual(seen["state"], "deploying")
        self.assertEqual(seen["target"]["image_id"], "sha256:new")
        self.assertEqual(seen["running"]["image_id"], "sha256:old")

    def test_state_rolled_back(self):
        docker = FakeDocker("sha256:old", "sha256:new", healthy=False)
        self.assertEqual(self.run_update(docker), 1)
        status = self.status()
        self.assertEqual(status["state"], "rolled_back")
        self.assertEqual(status["running"]["image_id"], "sha256:old")
        self.assertEqual(status["history"][0]["result"], "rolled_back")
        self.assertEqual(status["history"][0]["image_id"], "sha256:new")

    def test_state_skipped_bad_names_the_refused_image(self):
        docker = FakeDocker("sha256:old", "sha256:new", healthy=False)
        self.run_update(docker)
        self.run_update(FakeDocker("sha256:old", "sha256:new"))
        status = self.status()
        self.assertEqual(status["state"], "skipped_bad")
        self.assertEqual(status["target"]["image_id"], "sha256:new")
        self.assertEqual(len(status["history"]), 1)  # skipping is not a new attempt

    def test_state_pull_failed_keeps_running(self):
        self.run_update(FakeDocker("sha256:old", "sha256:new"))
        self.run_update(FakeDocker("sha256:new", "sha256:newer", pull_ok=False))
        status = self.status()
        self.assertEqual(status["state"], "pull_failed")
        self.assertEqual(status["running"]["image_id"], "sha256:new")

    def test_state_without_labels(self):
        self.run_update(FakeDocker("sha256:old", "sha256:new"))
        running = self.status()["running"]
        self.assertIsNone(running["version"])
        self.assertIsNone(running["revision"])

    def test_no_new_image_keeps_since_and_history(self):
        self.run_update(FakeDocker("sha256:old", "sha256:new"))
        first = self.status()
        self.run_update(FakeDocker("sha256:new", "sha256:new"))
        status = self.status()
        self.assertEqual(status["state"], "deployed")
        self.assertEqual(status["running"]["since"], first["running"]["since"])
        self.assertEqual(status["history"], first["history"])
        self.assertGreaterEqual(status["checked_at"], first["checked_at"])

    def test_history_keeps_last_20(self):
        for i in range(25):
            self.run_update(FakeDocker(f"sha256:{i}", f"sha256:{i + 1}"))
        history = self.status()["history"]
        self.assertEqual(len(history), 20)
        self.assertEqual(history[0]["image_id"], "sha256:25")

    def test_without_status_dir_nothing_is_written(self):
        update("portfolio", FakeDocker("sha256:old", "sha256:new"), self.state, timeout=1)
        self.assertEqual(list(self.status_dir.iterdir()), [])
