"""
Chaos / fault injection orchestrator for Uptime Kuma.

Runs four scenarios sequentially, each with the same shape:
    1. WARMUP   -> probe baseline for `warmup_s` seconds
    2. INJECT   -> trigger the fault, keep probing for `fault_s` seconds
    3. RECOVER  -> stop the fault, keep probing until first 2xx; record MTTR
    4. SETTLE   -> probe for `settle_s` seconds to see post-recovery health

Outputs per scenario:
    tests/experimental/results/chaos_<id>_raw.csv   (full probe trace)
    tests/experimental/results/chaos_<id>_summary.json
And a combined: chaos_summary.json

Usage:
    python3 run_chaos.py --scenario all
    python3 run_chaos.py --scenario C1
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from typing import Callable, List

# Import sibling probe_client without depending on package machinery
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_client import probe, Sample  # noqa: E402

CONTAINER = "uptime-kuma"
DEFAULT_BASE = "http://localhost:3001"
RESULTS_DIR = "tests/experimental/results"
PROBE_PATH = "/api/entry-page"


# --- Probe loop --------------------------------------------------------------

def probe_loop(url: str, hz: float, stop: threading.Event,
               sink: List[Sample]) -> None:
    interval = 1.0 / hz
    while not stop.is_set():
        sink.append(probe(url))
        time.sleep(interval)


# --- Fault implementations ---------------------------------------------------

def fault_pause(duration_s: int) -> None:
    subprocess.run(["docker", "pause", CONTAINER], check=True, capture_output=True)
    time.sleep(duration_s)
    subprocess.run(["docker", "unpause", CONTAINER], check=True, capture_output=True)


def fault_stop_start(duration_s: int) -> None:
    subprocess.run(["docker", "stop", CONTAINER], check=True, capture_output=True)
    time.sleep(max(duration_s - 2, 1))
    subprocess.run(["docker", "start", CONTAINER], check=True, capture_output=True)


def fault_cpu_stress(duration_s: int) -> None:
    """Burn CPU inside the container until duration elapses.
    Spawns 2*nproc busy loops to ensure saturation across all cores."""
    nproc = int(subprocess.run(["docker", "exec", CONTAINER, "nproc"],
                               capture_output=True, text=True).stdout.strip() or 4)
    workers = nproc * 2
    cmd = (f"for i in $(seq 1 {workers}); do "
           f"  (timeout {duration_s} sh -c 'while :; do :; done' &) ; "
           f"done; sleep {duration_s + 1}")
    p = subprocess.Popen(
        ["docker", "exec", CONTAINER, "sh", "-c", cmd],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(duration_s + 1)
    finally:
        try: p.wait(timeout=2)
        except Exception:
            try: p.kill()
            except Exception: pass


def fault_latency_proxy(duration_s: int, delay_ms: int = 200) -> None:
    """Spin up the latency proxy on :3002 for `duration_s` seconds.
    Caller probes :3002 instead of :3001 during this window."""
    cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "latency_proxy.py"),
           "--listen", "3002", "--upstream", "localhost:3001",
           "--delay-ms", str(delay_ms)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(duration_s)
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except Exception:
            proc.kill()


# --- Wait-for helpers --------------------------------------------------------

def wait_first_2xx(url: str, timeout_s: float = 30.0) -> float | None:
    """Return seconds to first 2xx, or None if it never recovers in window."""
    start = time.perf_counter()
    deadline = start + timeout_s
    while time.perf_counter() < deadline:
        s = probe(url, timeout_s=1.5)
        if 200 <= s.status < 300:
            return time.perf_counter() - start
        time.sleep(0.25)
    return None


# --- Summary -----------------------------------------------------------------

def summarize_window(samples: List[Sample], t_start: float, t_end: float) -> dict:
    win = [s for s in samples if t_start <= s.t < t_end]
    if not win:
        return {"requests": 0, "ok": 0, "errors": 0, "availability_pct": 0,
                "rt_avg_ms": 0, "rt_p95_ms": 0}
    ok = [s for s in win if 200 <= s.status < 400]
    errors = [s for s in win if not (200 <= s.status < 400)]
    durations = [s.elapsed_ms for s in win]
    durations_sorted = sorted(durations)
    p95 = durations_sorted[int(0.95 * (len(durations_sorted) - 1))]
    return {
        "requests": len(win),
        "ok": len(ok),
        "errors": len(errors),
        "availability_pct": round(100 * len(ok) / len(win), 2),
        "rt_avg_ms": round(statistics.fmean(durations), 2),
        "rt_p95_ms": round(p95, 2),
    }


def write_csv(samples: List[Sample], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "status", "elapsed_ms", "error"])
        for s in samples:
            w.writerow([round(s.t, 4), s.status, round(s.elapsed_ms, 2), s.error])


# --- Scenarios ---------------------------------------------------------------

SCENARIOS = {
    "C1": {
        "name": "API_downtime_pause",
        "warmup_s": 8, "fault_s": 20, "settle_s": 8,
        "fault_fn": lambda d: fault_pause(d),
        "url": f"{DEFAULT_BASE}{PROBE_PATH}",
    },
    "C2": {
        "name": "Container_crash_restart",
        "warmup_s": 8, "fault_s": 15, "settle_s": 12,
        "fault_fn": lambda d: fault_stop_start(d),
        "url": f"{DEFAULT_BASE}{PROBE_PATH}",
    },
    "C3": {
        "name": "Network_latency_200ms",
        "warmup_s": 8, "fault_s": 30, "settle_s": 8,
        "fault_fn": lambda d: fault_latency_proxy(d, 200),
        # Probe through the proxy port during the fault window
        "url": f"http://localhost:3002{PROBE_PATH}",
        "url_warm": f"{DEFAULT_BASE}{PROBE_PATH}",
        "url_settle": f"{DEFAULT_BASE}{PROBE_PATH}",
    },
    "C4": {
        "name": "CPU_stress",
        "warmup_s": 8, "fault_s": 30, "settle_s": 8,
        "fault_fn": lambda d: fault_cpu_stress(d),
        "url": f"{DEFAULT_BASE}{PROBE_PATH}",
    },
}


def run_scenario(sid: str, hz: float = 5.0) -> dict:
    s = SCENARIOS[sid]
    print(f"\n[chaos {sid}] {s['name']}")
    samples: List[Sample] = []
    stop = threading.Event()
    url_warm = s.get("url_warm", s["url"])
    url_fault = s["url"]
    url_settle = s.get("url_settle", s["url"])

    # warmup
    t0 = time.time()
    th = threading.Thread(target=probe_loop, args=(url_warm, hz, stop, samples), daemon=True)
    th.start()
    time.sleep(s["warmup_s"])
    t_warm_end = time.time()

    # switch to fault url (matters for C3 — proxy on :3002)
    stop.set(); th.join()
    samples_fault: List[Sample] = []
    stop = threading.Event()
    th = threading.Thread(target=probe_loop, args=(url_fault, hz, stop, samples_fault), daemon=True)
    th.start()
    s["fault_fn"](s["fault_s"])
    t_fault_end = time.time()
    stop.set(); th.join()

    # measure recovery time on the original (non-proxy) URL
    mttr = wait_first_2xx(url_settle, timeout_s=15.0)
    t_recover = time.time()

    # settle
    samples_settle: List[Sample] = []
    stop = threading.Event()
    th = threading.Thread(target=probe_loop, args=(url_settle, hz, stop, samples_settle), daemon=True)
    th.start()
    time.sleep(s["settle_s"])
    stop.set(); th.join()
    t_settle_end = time.time()

    # combine, write csv
    all_samples = samples + samples_fault + samples_settle
    raw_path = os.path.join(RESULTS_DIR, f"chaos_{sid}_{s['name']}_raw.csv")
    write_csv(all_samples, raw_path)

    summary = {
        "scenario": sid,
        "name": s["name"],
        "warmup":  summarize_window(samples,        t0, t_warm_end),
        "during_fault": summarize_window(samples_fault, t_warm_end, t_fault_end),
        "settle":  summarize_window(samples_settle, t_recover, t_settle_end),
        "mttr_s": round(mttr, 2) if mttr is not None else None,
        "raw_csv": raw_path,
    }
    print(f"  warmup avail: {summary['warmup']['availability_pct']}%  "
          f"during fault: {summary['during_fault']['availability_pct']}%  "
          f"settle: {summary['settle']['availability_pct']}%  "
          f"MTTR: {summary['mttr_s']}s")
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="all", choices=["all", "C1", "C2", "C3", "C4"])
    args = p.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    keys = ["C1", "C2", "C3", "C4"] if args.scenario == "all" else [args.scenario]
    out = {}
    for k in keys:
        out[k] = run_scenario(k)
    with open(os.path.join(RESULTS_DIR, "chaos_summary.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[done] -> {os.path.join(RESULTS_DIR, 'chaos_summary.json')}")


if __name__ == "__main__":
    main()
