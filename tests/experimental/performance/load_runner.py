"""
Stdlib-only load generator for Uptime Kuma performance tests.

Why stdlib? The graded WSL environment has no `pip`. Locust/k6 would be
preferred in a Docker-based CI run; this runner produces equivalent
percentile metrics and emits CSV that any plotting tool can ingest.

Scenarios:
    S1 normal     : steady 10 VU, 60s
    S2 peak       : steady 50 VU, 60s
    S3 spike      : ramp 5 -> 100 VU in 4 steps over 60s
    S4 endurance  : steady 20 VU, 300s (default; --short cuts it to 60s)

Each "VU" is a thread that repeatedly hits a randomly-chosen endpoint and
records (timestamp, endpoint, status, elapsed_ms, error).

Usage:
    python3 load_runner.py --scenario S1 --base-url http://localhost:3001
    python3 load_runner.py --scenario all --short --out ../results
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List


ENDPOINTS = [
    # Public, unauthenticated endpoints exposed by Uptime Kuma 2.x
    ("status_page",     "/api/status-page/main"),                # 404 JSON when slug absent — exercises router + DB lookup
    ("heartbeat",       "/api/status-page/heartbeat/main"),      # 200 JSON, includes DB heartbeat retrieval
    ("badge",           "/api/badge/1/status"),                  # 200 SVG, generates response per-request
    ("entry_page",      "/api/entry-page"),                      # 200 JSON, settings lookup
]


@dataclass
class Sample:
    t: float            # seconds since test start
    endpoint: str
    status: int         # 0 == network error / timeout
    elapsed_ms: float
    error: str = ""


@dataclass
class Scenario:
    name: str
    schedule: List[tuple]   # list of (duration_s, concurrency)
    description: str = ""

    @property
    def total_duration(self) -> int:
        return sum(d for d, _ in self.schedule)


def make_scenarios(short: bool) -> dict:
    endurance_d = 60 if short else 300
    return {
        "S1": Scenario("S1_normal",   [(60, 10)],                          "10 VU steady, 60s"),
        "S2": Scenario("S2_peak",     [(60, 50)],                          "50 VU steady, 60s"),
        "S3": Scenario("S3_spike",    [(15, 5), (15, 25), (15, 60), (15, 100)], "ramp 5->100"),
        "S4": Scenario("S4_endurance",[(endurance_d, 20)],                 f"20 VU for {endurance_d}s"),
    }


def hit_once(base_url: str, samples: list, start_time: float, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        name, path = random.choice(ENDPOINTS)
        url = base_url + path
        t0 = time.perf_counter()
        status = 0
        err = ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kuma-perf/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()  # drain body
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
            err = f"http_{e.code}"
        except Exception as e:
            err = type(e).__name__
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        samples.append(Sample(time.time() - start_time, name, status, elapsed_ms, err))


def run_scenario(scenario: Scenario, base_url: str) -> List[Sample]:
    samples: list = []
    start = time.time()

    for duration, vus in scenario.schedule:
        stop = threading.Event()
        with ThreadPoolExecutor(max_workers=vus) as ex:
            for _ in range(vus):
                ex.submit(hit_once, base_url, samples, start, stop)
            time.sleep(duration)
            stop.set()
        # ThreadPoolExecutor context exit waits for in-flight requests
    return samples


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(samples: List[Sample]) -> dict:
    durations = [s.elapsed_ms for s in samples]
    # 4xx = handled client error (still a successful round-trip).
    # Only count 5xx and connection failures as failures for SLO purposes.
    server_errors = [s for s in samples if s.status >= 500 or s.status == 0]
    client_4xx = [s for s in samples if 400 <= s.status < 500]
    ok = [s for s in samples if 200 <= s.status < 400]
    if samples:
        wall = max(s.t for s in samples) - min(s.t for s in samples)
    else:
        wall = 0.0
    rps = len(samples) / wall if wall > 0 else 0.0
    return {
        "requests": len(samples),
        "ok_2xx_3xx": len(ok),
        "client_4xx": len(client_4xx),
        "server_errors": len(server_errors),
        "error_rate_pct": round(100 * len(server_errors) / max(len(samples), 1), 3),
        "rps": round(rps, 2),
        "duration_s": round(wall, 2),
        "rt_avg_ms": round(statistics.fmean(durations), 2) if durations else 0,
        "rt_median_ms": round(statistics.median(durations), 2) if durations else 0,
        "rt_p95_ms": round(percentile(durations, 0.95), 2),
        "rt_p99_ms": round(percentile(durations, 0.99), 2),
        "rt_max_ms": round(max(durations), 2) if durations else 0,
    }


def per_endpoint_breakdown(samples: List[Sample]) -> dict:
    by_ep: dict = {}
    for s in samples:
        by_ep.setdefault(s.endpoint, []).append(s)
    return {ep: summarize(rows) for ep, rows in by_ep.items()}


def write_csv(samples: List[Sample], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "endpoint", "status", "elapsed_ms", "error"])
        for s in samples:
            w.writerow([round(s.t, 4), s.endpoint, s.status, round(s.elapsed_ms, 2), s.error])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="all", choices=["S1", "S2", "S3", "S4", "all"])
    p.add_argument("--base-url", default="http://localhost:3001")
    p.add_argument("--out", default="tests/experimental/results")
    p.add_argument("--short", action="store_true", help="cut endurance test to 60s for quick smoke")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    scenarios = make_scenarios(args.short)
    keys = list(scenarios) if args.scenario == "all" else [args.scenario]

    final = {}
    for k in keys:
        sc = scenarios[k]
        print(f"\n[run] {sc.name}: {sc.description}")
        samples = run_scenario(sc, args.base_url)
        summary = summarize(samples)
        endpoints = per_endpoint_breakdown(samples)
        print(f"  -> requests={summary['requests']}  rps={summary['rps']}  "
              f"5xx_err={summary['error_rate_pct']}%  4xx={summary['client_4xx']}  "
              f"p95={summary['rt_p95_ms']}ms")
        write_csv(samples, os.path.join(args.out, f"perf_{sc.name}_raw.csv"))
        final[sc.name] = {"summary": summary, "by_endpoint": endpoints}

    with open(os.path.join(args.out, "perf_summary.json"), "w") as f:
        json.dump(final, f, indent=2)
    print(f"\n[done] summary -> {os.path.join(args.out, 'perf_summary.json')}")


if __name__ == "__main__":
    main()
