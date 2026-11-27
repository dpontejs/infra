"""Tests for status_snapshot: health.json for the deploys page, with Docker, /proc and Kuma faked."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from status_snapshot import host_stats, kuma_sites, parse_kuma_metrics, snapshot

INSPECT = [
    {
        "Name": "/today-today-1",
        "RestartCount": 0,
        "State": {"Status": "running", "StartedAt": "2026-11-26T22:42:10Z", "Health": {"Status": "healthy"}},
        "Config": {"Image": "ghcr.io/dpontejs/today:main"},
    },
    {
        "Name": "/caddy-caddy-1",
        "RestartCount": 2,
        "State": {"Status": "exited", "StartedAt": "2026-11-25T07:31:56Z"},
        "Config": {"Image": "caddy:2.11.7"},
    },
]

METRICS = """# HELP monitor_status Monitor Status (1 = UP, 0= DOWN, 2= PENDING, 3= MAINTENANCE)
# TYPE monitor_status gauge
monitor_status{monitor_id="3",monitor_name="Beszel hub",monitor_type="http",monitor_url="http://beszel:8090/api/health",monitor_hostname="null",monitor_port="null"} 1
monitor_status{monitor_name="containers",monitor_type="push",monitor_url="https://",monitor_hostname="null",monitor_port="null"} 0
monitor_response_time{monitor_name="Beszel hub",monitor_type="http"} 12
"""


def fake_runner(inspect_output, returncode=1):
    """`docker inspect` prints the containers it found as JSON and exits 1 if any name is missing."""

    def run(cmd):
        return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(inspect_output), stderr="")

    return run


def write_proc(root, cpu="cpu  100 0 100 800 0 0 0 0 0 0"):
    (root / "stat").write_text(f"{cpu}\ncpu0 1 2 3 4\n")
    (root / "loadavg").write_text("0.70 0.43 0.52 1/300 12345\n")
    (root / "uptime").write_text("157000.12 300000.00\n")
    (root / "meminfo").write_text(
        "MemTotal:        4000000 kB\nMemFree:          300000 kB\nMemAvailable:    2600000 kB\n"
        "SwapTotal:       2000000 kB\nSwapFree:        1960000 kB\n"
    )


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.proc = Path(tempfile.mkdtemp())
        self.status = Path(tempfile.mkdtemp())
        write_proc(self.proc)

    def run_snapshot(self, watched=("today-today-1", "caddy-caddy-1", "pathoxp-mcp-1"), sites=None):
        snapshot(
            list(watched),
            self.status,
            runner=fake_runner(INSPECT),
            proc=self.proc,
            disk_path="/",
            sites=lambda: sites,
        )
        return json.loads((self.status / "health.json").read_text())

    def test_health_lists_running_stopped_and_missing(self):
        containers = {c["name"]: c for c in self.run_snapshot()["containers"]}
        self.assertEqual(containers["today-today-1"]["state"], "running")
        self.assertEqual(containers["today-today-1"]["health"], "healthy")
        self.assertEqual(containers["caddy-caddy-1"]["state"], "exited")
        self.assertIsNone(containers["caddy-caddy-1"]["health"])  # no healthcheck
        self.assertEqual(containers["caddy-caddy-1"]["restarts"], 2)
        self.assertEqual(containers["pathoxp-mcp-1"]["state"], "missing")

    def test_containers_keep_the_watched_order(self):
        names = [c["name"] for c in self.run_snapshot()["containers"]]
        self.assertEqual(names, ["today-today-1", "caddy-caddy-1", "pathoxp-mcp-1"])

    def test_host_memory_swap_load_uptime(self):
        host = self.run_snapshot()["host"]
        self.assertEqual(host["mem_pct"], 35.0)  # 1 - 2.6/4.0
        self.assertEqual(host["swap_pct"], 2.0)
        self.assertEqual(host["load"], [0.7, 0.43, 0.52])
        self.assertEqual(host["uptime_s"], 157000)
        self.assertTrue(0 <= host["disk_pct"] <= 100)

    def test_first_run_has_no_cpu_pct(self):
        self.assertIsNone(self.run_snapshot()["host"]["cpu_pct"])

    def test_cpu_pct_from_previous_sample(self):
        self.run_snapshot()
        # +300 busy (user+system), +100 idle since the first sample: 75 %.
        write_proc(self.proc, cpu="cpu  250 0 250 900 0 0 0 0 0 0")
        self.assertEqual(self.run_snapshot()["host"]["cpu_pct"], 75.0)

    def test_sites_from_kuma(self):
        sites = [{"name": "Beszel hub", "up": True}]
        self.assertEqual(self.run_snapshot(sites=sites)["sites"], sites)

    def test_kuma_unreachable_gives_null_sites(self):
        self.assertIsNone(self.run_snapshot(sites=None)["sites"])

    def test_file_is_world_readable(self):
        self.run_snapshot()
        self.assertEqual((self.status / "health.json").stat().st_mode & 0o777, 0o644)


class KumaTest(unittest.TestCase):
    def test_parse_kuma_metrics(self):
        self.assertEqual(
            parse_kuma_metrics(METRICS),
            [{"name": "Beszel hub", "up": True, "status": 1}, {"name": "containers", "up": False, "status": 0}],
        )

    def test_kuma_sites_without_key_is_none(self):
        self.assertIsNone(kuma_sites(runner=fake_runner([]), kuma_container="uptime-kuma-uptime-kuma-1", key=""))

    def test_kuma_sites_unreachable_is_none(self):
        def ip_runner(cmd):
            return subprocess.CompletedProcess(cmd, 0, stdout="127.0.0.1\n", stderr="")

        # Nothing listens on 127.0.0.1:1; the failure must not raise.
        self.assertIsNone(
            kuma_sites(runner=ip_runner, kuma_container="kuma", key="k", port=1, timeout=0.5)
        )


class HostStatsTest(unittest.TestCase):
    def test_missing_proc_files_give_nulls_not_crash(self):
        stats = host_stats(Path(tempfile.mkdtemp()), "/", previous=None)[0]
        self.assertIsNone(stats["mem_pct"])
        self.assertIsNone(stats["load"])


if __name__ == "__main__":
    unittest.main()
