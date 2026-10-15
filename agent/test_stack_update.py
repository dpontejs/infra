"""Tests for stack_update.update(): the deploy decision logic, with Docker faked in memory."""

import tempfile
import unittest
from pathlib import Path

from stack_update import rollback_ref, update

REF = "ghcr.io/dpontejs/portfolio:main"
ROLLBACK = "ghcr.io/dpontejs/portfolio:rollback"


class FakeDocker:
    """In-memory stand-in for the Docker CLI wrapper: records every action.

    Mimics Docker 29's containerd image store: an image exists only while some tag points to it.
    Once `pull` moves the tag away, the old image can't be tagged again, even if a container still
    runs it (found by agent/integration_stack_update.py).
    """

    def __init__(self, running, remote, healthy=True, pull_ok=True):
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
