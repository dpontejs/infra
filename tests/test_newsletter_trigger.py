"""newsletter-trigger with fake `docker` and `curl` on PATH: dispatch each due edition once."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ansible/roles/newsletter_trigger/files/newsletter-trigger"
DUE = "pre\t2026-10-18\tPré-jogo — 18/10/2026\n"


class TriggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.state = self.dir / "state"
        self.state.mkdir()
        self.curl_log = self.dir / "curl.log"
        self.fake("curl", f'cat >> "{self.curl_log}"; echo "$@" >> "{self.curl_log}"; exit ${{CURL_EXIT:-0}}')

    def fake(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n")
        path.chmod(0o755)

    def run_trigger(self, due: str, curl_exit: int = 0) -> subprocess.CompletedProcess:
        (self.dir / "due.txt").write_text(due)
        self.fake("docker", f'cat "{self.dir / "due.txt"}"')
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "STATE_DIRECTORY": str(self.state),
            "COMPOSE_FILE": "/opt/stacks/flamengo-news/compose.yml",
            "GITHUB_REPO": "dpontejs/flamengo-news",
            "GITHUB_TOKEN": "secret-token",
            "CURL_EXIT": str(curl_exit),
        }
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def dispatched(self) -> str:
        return self.curl_log.read_text() if self.curl_log.exists() else ""

    def test_nothing_due_dispatches_nothing(self) -> None:
        result = self.run_trigger("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dispatched(), "")

    def test_due_edition_is_dispatched_with_its_kind_and_date(self) -> None:
        result = self.run_trigger(DUE)
        self.assertEqual(result.returncode, 0, result.stderr)
        sent = self.dispatched()
        self.assertIn('"edition":"pre","date":"2026-10-18"', sent)
        self.assertIn('"skip_if_sent":"true"', sent)
        self.assertIn("Authorization: Bearer secret-token", sent)  # via stdin config, not argv
        self.assertNotIn("secret-token", sent.splitlines()[-1])  # the argv line
        self.assertEqual((self.state / "dispatched").read_text(), "Pré-jogo — 18/10/2026\n")

    def test_same_edition_is_dispatched_once(self) -> None:
        self.run_trigger(DUE)
        first = self.dispatched()
        result = self.run_trigger(DUE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dispatched(), first)
        self.assertIn("already dispatched", result.stdout)

    def test_failed_dispatch_is_retried_on_the_next_tick(self) -> None:
        result = self.run_trigger(DUE, curl_exit=22)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.state / "dispatched").read_text(), "")


if __name__ == "__main__":
    unittest.main()
