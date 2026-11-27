#!/usr/bin/env python3
"""status-snapshot: writes <status-dir>/health.json for the deploys page (docs/features/deploys.md).

Run every minute by container-watch.service, right after the Uptime Kuma push: host CPU, memory,
swap, disk and load; state and health of every watched container; Uptime Kuma monitors from its
/metrics endpoint. Every part degrades to null instead of failing, so the page always gets a file.

Standard library only: it runs with the server's system Python.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
CPU_SAMPLE = ".cpu-sample"


def run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)


def containers(watched: list[str], runner: Runner) -> list[dict]:
    """One entry per watched name, in order; names Docker does not know are "missing"."""
    # Exits 1 when some name is missing but still prints the ones it found.
    result = runner(["docker", "inspect", *watched])
    try:
        found = {c["Name"].lstrip("/"): c for c in json.loads(result.stdout or "[]")}
    except ValueError:
        found = {}
    out = []
    for name in watched:
        info = found.get(name)
        if info is None:
            out.append({"name": name, "state": "missing", "health": None, "started_at": None, "restarts": None, "image": None})
            continue
        state = info.get("State", {})
        out.append(
            {
                "name": name,
                "state": state.get("Status"),
                "health": (state.get("Health") or {}).get("Status"),
                "started_at": state.get("StartedAt"),
                "restarts": info.get("RestartCount"),
                "image": info.get("Config", {}).get("Image"),
            }
        )
    return out


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def host_stats(proc: Path, disk_path: str, previous: list[int] | None) -> tuple[dict, list[int] | None]:
    """Returns (stats, cpu sample to keep for the next run)."""
    stats: dict = {"cpu_pct": None, "load": None, "mem_pct": None, "swap_pct": None, "disk_pct": None, "uptime_s": None}

    sample = None
    stat = _read(proc / "stat")
    if stat:
        fields = [int(x) for x in stat.splitlines()[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
        sample = [sum(fields), idle]
        if previous and sample[0] > previous[0]:
            total, idle_delta = sample[0] - previous[0], sample[1] - previous[1]
            stats["cpu_pct"] = round(100 * (total - idle_delta) / total, 1)

    loadavg = _read(proc / "loadavg")
    if loadavg:
        stats["load"] = [float(x) for x in loadavg.split()[:3]]

    meminfo = _read(proc / "meminfo")
    if meminfo:
        mem = {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in meminfo.splitlines() if ":" in line)}
        if mem.get("MemTotal"):
            stats["mem_pct"] = round(100 * (1 - mem.get("MemAvailable", 0) / mem["MemTotal"]), 1)
        if mem.get("SwapTotal"):
            stats["swap_pct"] = round(100 * (1 - mem.get("SwapFree", 0) / mem["SwapTotal"]), 1)

    uptime = _read(proc / "uptime")
    if uptime:
        stats["uptime_s"] = int(float(uptime.split()[0]))

    try:
        fs = os.statvfs(disk_path)
        used = (fs.f_blocks - fs.f_bfree) * fs.f_frsize
        usable = used + fs.f_bavail * fs.f_frsize  # same formula as `df`
        stats["disk_pct"] = round(100 * used / usable, 1) if usable else None
    except OSError:
        pass
    return stats, sample


METRIC = re.compile(r'^monitor_status\{[^}]*monitor_name="(?P<name>(?:[^"\\]|\\.)*)"[^}]*\}\s+(?P<value>\d+)')


def parse_kuma_metrics(text: str) -> list[dict]:
    """monitor_status: 1 = up, 0 = down, 2 = pending, 3 = maintenance."""
    sites = []
    for line in text.splitlines():
        match = METRIC.match(line)
        if match:
            value = int(match["value"])
            sites.append({"name": match["name"].replace('\\"', '"'), "up": value == 1, "status": value})
    return sites


def kuma_sites(runner: Runner, kuma_container: str, key: str, port: int = 3001, timeout: float = 5) -> list[dict] | None:
    """Reads Kuma's /metrics through its IP on the "web" network (the public domain answers 403 here)."""
    if not key:
        return None
    ip = runner(["docker", "inspect", "-f", '{{(index .NetworkSettings.Networks "web").IPAddress}}', kuma_container])
    address = ip.stdout.strip() if ip.returncode == 0 else ""
    if not address:
        return None
    request = urllib.request.Request(
        f"http://{address}:{port}/metrics",
        headers={"Authorization": "Basic " + base64.b64encode(f":{key}".encode()).decode()},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return parse_kuma_metrics(response.read().decode())
    except (OSError, ValueError):
        return None


def snapshot(
    watched: list[str],
    status_dir: Path,
    runner: Runner = run,
    proc: Path = Path("/proc"),
    disk_path: str = "/",
    sites: Callable[[], list[dict] | None] = lambda: None,
) -> None:
    sample_file = status_dir / CPU_SAMPLE
    try:
        previous = json.loads(sample_file.read_text())
    except (OSError, ValueError):
        previous = None
    host, sample = host_stats(proc, disk_path, previous)

    data = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "host": host,
        "containers": containers(watched, runner),
        "sites": sites(),
    }
    status_dir.mkdir(parents=True, exist_ok=True)
    if sample:
        sample_file.write_text(json.dumps(sample))
    tmp = status_dir / "health.json.tmp"
    tmp.write_text(json.dumps(data, indent=1))
    os.chmod(tmp, 0o644)
    tmp.replace(status_dir / "health.json")  # atomic: the page never reads half a file


def main() -> int:
    watched = os.environ.get("WATCHED_CONTAINERS", "").split()
    status_dir = Path(os.environ.get("STATUS_DIR", "/var/lib/status"))
    kuma = os.environ.get("KUMA_CONTAINER", "uptime-kuma-uptime-kuma-1")
    key = os.environ.get("KUMA_METRICS_KEY", "")
    snapshot(watched, status_dir, sites=lambda: kuma_sites(run, kuma, key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
