"""Integration test for stack-update against a real Docker daemon and a local registry.

Slower than the unit tests (builds images, waits for healthchecks): `make test-integration`, and CI.
Verifies what the unit tests can't: that `compose up --wait` really reports an unhealthy container and
that retagging the previous image really brings the old version back.
"""

import subprocess
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

from stack_update import Docker, update

REGISTRY_PORT = 5055
NAME = f"stack-update-it-{uuid.uuid4().hex[:8]}"
REF = f"127.0.0.1:{REGISTRY_PORT}/{NAME}:main"


def sh(*cmd: str, stdin: str | None = None) -> str:
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=True).stdout.strip()


def publish(version: str, healthy: bool) -> str:
    """Builds and pushes an image under REF; returns its image ID."""
    dockerfile = textwrap.dedent(f"""
        FROM busybox:1.37
        LABEL version="{version}"
        HEALTHCHECK --interval=1s --timeout=1s --retries=2 CMD {"true" if healthy else "false"}
        CMD ["sleep", "3600"]
    """)
    sh("docker", "build", "-q", "-t", REF, "-", stdin=dockerfile)
    sh("docker", "push", "-q", REF)
    return sh("docker", "image", "inspect", "--format", "{{.Id}}", REF)


class StackUpdateIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = f"{NAME}-registry"
        sh("docker", "run", "-d", "--name", cls.registry, "-p", f"127.0.0.1:{REGISTRY_PORT}:5000", "registry:3")
        cls.stacks = Path(tempfile.mkdtemp())
        (cls.stacks / NAME).mkdir()
        (cls.stacks / NAME / "compose.yml").write_text(f"services:\n  app:\n    image: {REF}\n")
        cls.state = Path(tempfile.mkdtemp())
        cls.docker = Docker(cls.stacks / NAME, "app")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "compose", "--project-directory", str(cls.stacks / NAME), "down"], capture_output=True)
        subprocess.run(["docker", "rm", "-f", cls.registry], capture_output=True)
        subprocess.run(["docker", "image", "rm", "-f", REF], capture_output=True)

    def test_deploy_upgrade_rollback_and_skip(self):
        v1 = publish("1", healthy=True)
        self.assertEqual(update(NAME, self.docker, self.state, timeout=30), 0)
        self.assertEqual(self.docker.running_image_id(), v1, "first deploy")

        v2 = publish("2", healthy=True)
        self.assertEqual(update(NAME, self.docker, self.state, timeout=30), 0)
        self.assertEqual(self.docker.running_image_id(), v2, "healthy upgrade")

        self.assertEqual(update(NAME, self.docker, self.state, timeout=30), 0)
        self.assertEqual(self.docker.running_image_id(), v2, "no new image: nothing changes")

        v3 = publish("3", healthy=False)
        self.assertEqual(update(NAME, self.docker, self.state, timeout=30), 1)
        self.assertEqual(self.docker.running_image_id(), v2, "unhealthy image rolled back")
        self.assertIn(v3, (self.state / f"{NAME}.bad").read_text().split())

        self.assertEqual(update(NAME, self.docker, self.state, timeout=30), 0)
        self.assertEqual(self.docker.running_image_id(), v2, "known bad image skipped")


if __name__ == "__main__":
    unittest.main()
