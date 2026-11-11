"""geral-trigger with fake `docker` and `curl` on PATH: dispatch each due team edition once."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ansible/roles/geral_trigger/files/geral-trigger"
VASCO = "vasco\tpre\t2026-10-18\tPré-jogo — 18/10/2026\n"
NAUTICO = "nautico\tpre\t2026-10-18\tPré-jogo — 18/10/2026\n"


class GeralTriggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.state = self.dir / "state"
        self.state.mkdir()
        self.curl_log = self.dir / "curl.log"
        self.fake(
            "curl",
            f'echo "--- $*" >> "{self.curl_log}"; cat >> "{self.curl_log}"; '
            f'[ -n "$FAIL_TEAM" ] && echo "$*" | grep -q "\\"team\\":\\"$FAIL_TEAM\\"" && exit 22; exit 0',
        )

    def fake(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n")
        path.chmod(0o755)

    def run_trigger(self, due: str, fail_team: str = "") -> subprocess.CompletedProcess:
        (self.dir / "due.txt").write_text(due)
        self.fake("docker", f'cat "{self.dir / "due.txt"}"')
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "STATE_DIRECTORY": str(self.state),
            "COMPOSE_FILE": "/opt/stacks/geral/compose.yml",
            "GITHUB_REPO": "dpontejs/geral",
            "GITHUB_TOKEN": "secret-token",
            "FAIL_TEAM": fail_team,
        }
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def dispatched(self) -> str:
        return self.curl_log.read_text() if self.curl_log.exists() else ""

    def calls(self) -> list[str]:
        return [line for line in self.dispatched().splitlines() if line.startswith("--- ")]

    def test_nothing_due_dispatches_nothing(self) -> None:
        result = self.run_trigger("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dispatched(), "")

    def test_trigger_dispatches_each_team_once(self) -> None:
        result = self.run_trigger(VASCO)
        self.assertEqual(result.returncode, 0, result.stderr)
        [call] = self.calls()
        self.assertIn('"team":"vasco","edition":"pre","date":"2026-10-18"', call)
        self.assertIn('"dry_run":"false","skip_if_sent":"true"', call)
        self.assertIn("/repos/dpontejs/geral/actions/workflows/newsletter.yml/dispatches", call)

        again = self.run_trigger(VASCO)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("already dispatched", again.stdout)

    def test_trigger_same_label_two_teams_are_both_dispatched(self) -> None:
        result = self.run_trigger(VASCO + NAUTICO)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(
            (self.state / "dispatched").read_text(),
            "vasco|Pré-jogo — 18/10/2026\nnautico|Pré-jogo — 18/10/2026\n",
        )

    def test_trigger_token_stays_out_of_argv(self) -> None:
        self.run_trigger(VASCO)
        self.assertIn("Authorization: Bearer secret-token", self.dispatched())  # via stdin config
        self.assertNotIn("secret-token", "\n".join(self.calls()))

    def test_failed_team_is_retried_next_tick_and_does_not_block_the_others(self) -> None:
        result = self.run_trigger(VASCO + NAUTICO, fail_team="vasco")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            (self.state / "dispatched").read_text(), "nautico|Pré-jogo — 18/10/2026\n"
        )


if __name__ == "__main__":
    unittest.main()
