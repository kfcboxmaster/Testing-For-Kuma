"""
Stdlib resource sampler — Python equivalent of sample_resources.sh.
Runs on Linux, macOS, and Windows (cmd / PowerShell) with no extra deps.

Usage:
    python sample_resources.py 60 results/perf_resources.csv
    python sample_resources.py 60 results/perf_resources.csv uptime-kuma
"""
from __future__ import annotations
import csv
import re
import subprocess
import sys
import time


def parse_mem_to_mib(raw: str) -> float:
    """'123.4MiB' -> 123.4 ; '1.5GiB' -> 1536.0 ; '512KiB' -> 0.5"""
    raw = raw.strip()
    m = re.match(r"([\d.]+)\s*([KMG]?i?B)", raw, re.IGNORECASE)
    if not m:
        return 0.0
    num = float(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("g"):
        return num * 1024
    if unit.startswith("k"):
        return num / 1024
    return num  # MiB / MB


def sample_once(container: str) -> tuple[float, float, float] | None:
    """Return (cpu_pct, mem_mib, mem_pct) or None if docker stats failed."""
    cmd = ["docker", "stats", "--no-stream",
           "--format", "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}", container]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    line = out.stdout.strip()
    if not line:
        return None
    try:
        cpu_str, mem_usage, mem_pct_str = line.split("|")
    except ValueError:
        return None
    cpu = float(cpu_str.replace("%", "").strip())
    used = mem_usage.split("/")[0].strip()  # "123.4MiB / 15.52GiB" -> "123.4MiB"
    mem_mib = parse_mem_to_mib(used)
    mem_pct = float(mem_pct_str.replace("%", "").strip())
    return cpu, mem_mib, mem_pct


def main() -> None:
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    out_path = sys.argv[2] if len(sys.argv) > 2 else "resources.csv"
    container = sys.argv[3] if len(sys.argv) > 3 else "uptime-kuma"

    deadline = time.time() + duration
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "cpu_pct", "mem_mib", "mem_pct"])
        while time.time() < deadline:
            row = sample_once(container)
            if row is not None:
                w.writerow([int(time.time()), row[0], round(row[1], 2), row[2]])
                f.flush()
            time.sleep(2)
    print(f"[done] -> {out_path}")


if __name__ == "__main__":
    main()
