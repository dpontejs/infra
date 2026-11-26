"""container-watch with fake `docker` and `curl` on PATH: push up/down to the Uptime Kuma monitor."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ansible/roles/container_watch/files/container-watch"
WATCHED = "caddy-caddy-1 today-today-1 pathoxp-mcp-1"


class ContainerWatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.curl_log = self.dir / "curl.log"
        self.fake(
            "curl",
            f'echo "--- $*" >> "{self.curl_log}"; cat >> "{self.curl_log}"; exit ${{CURL_EXIT:-0}}',
        )

    def fake(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n")
        path.chmod(0o755)

    def run_watch(self, states: dict[str, str], curl_exit: int = 0) -> subprocess.CompletedProcess:
        """states: container -> "true"/"false" (State.Running); absent containers do not exist."""
        lines = "".join(f"{name} {running}\\n" for name, running in states.items())
        # `docker inspect` prints the containers it found and exits 1 if any name is missing.
        missing = any(name not in states for name in WATCHED.split())
        self.fake(
            "docker",
            'if [ "$1" = inspect ] && [ "$2" = -f ] && [[ "$3" == *IPAddress* ]]; then echo 172.18.0.9; exit 0; fi\n'
            f'printf "{lines}"; exit {1 if missing else 0}',
        )
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "WATCHED_CONTAINERS": WATCHED,
            "KUMA_CONTAINER": "uptime-kuma-uptime-kuma-1",
            "PUSH_TOKEN": "secret-push-token",
            "CURL_EXIT": str(curl_exit),
        }
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def pushed(self) -> str:
        return self.curl_log.read_text() if self.curl_log.exists() else ""

    def test_all_running_pushes_up(self) -> None:
        result = self.run_watch({n: "true" for n in WATCHED.split()})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status=up", self.pushed())
        self.assertIn('url = "http://172.18.0.9:3001/api/push/secret-push-token"', self.pushed())

    def test_stopped_container_pushes_down_with_its_name(self) -> None:
        result = self.run_watch({"caddy-caddy-1": "true", "today-today-1": "false", "pathoxp-mcp-1": "true"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status=down", self.pushed())
        self.assertIn("today-today-1", self.pushed())
        self.assertNotIn("caddy-caddy-1", self.pushed())

    def test_missing_container_counts_as_stopped(self) -> None:
        result = self.run_watch({"caddy-caddy-1": "true", "today-today-1": "true"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status=down", self.pushed())
        self.assertIn("pathoxp-mcp-1", self.pushed())

    def test_token_stays_out_of_argv(self) -> None:
        self.run_watch({n: "true" for n in WATCHED.split()})
        calls = [line for line in self.pushed().splitlines() if line.startswith("--- ")]
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret-push-token", calls[0])

    def test_failed_push_exits_non_zero(self) -> None:
        result = self.run_watch({n: "true" for n in WATCHED.split()}, curl_exit=7)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
