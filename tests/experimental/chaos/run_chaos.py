"""
Chaos / fault injection orchestrator for Uptime Kuma.

--- WHAT IS CHAOS TESTING? ---
Chaos testing (also called fault injection) is the practice of deliberately
breaking things in a controlled way to see how your system responds.
The idea comes from Netflix's "Chaos Monkey" — a tool that randomly killed
servers in production to force engineers to build resilient systems.

The core question chaos testing answers:
    "What happens to my system when reality doesn't cooperate?"

--- HOW THIS SCRIPT WORKS ---
Every scenario follows the same 4-phase structure:
    1. WARMUP   -> probe baseline for `warmup_s` seconds
                   (establishes "healthy" behaviour before anything breaks)
    2. INJECT   -> trigger the fault, keep probing for `fault_s` seconds
                   (measures how badly the system degrades)
    3. RECOVER  -> stop the fault, probe until first 2xx; record MTTR
                   (MTTR = Mean Time To Recovery, the key resilience metric)
    4. SETTLE   -> probe for `settle_s` seconds to confirm full recovery
                   (checks there's no lingering damage after the fault ends)

Outputs per scenario:
    tests/experimental/results/chaos_<id>_raw.csv   (full probe trace)
    tests/experimental/results/chaos_<id>_summary.json
And a combined: chaos_summary.json

Usage:
    python3 run_chaos.py --scenario all
    python3 run_chaos.py --scenario C1
"""
from __future__ import annotations  # Allows using "float | None" syntax on older Python 3.9

import argparse       # Standard library for parsing command-line arguments like --scenario C1
import csv            # For writing results to CSV files
import json           # For writing summary data as human-readable JSON
import os             # For file paths and directory creation
import statistics     # For fmean() (fast mean) — part of stdlib since Python 3.8
import subprocess     # KEY: lets Python run shell commands like "docker pause uptime-kuma"
import sys            # For sys.path manipulation (see import hack below)
import threading      # KEY: allows the probe loop to run CONCURRENTLY with fault injection
import time           # For sleep(), perf_counter() (high-resolution timing), time()
from dataclasses import asdict   # Converts a dataclass instance to a plain dict (for JSON)
from typing import Callable, List

# --- WHY THIS IMPORT TRICK? ---
# Python's import system normally requires a package structure (__init__.py files).
# Since probe_client.py is just a sibling file in the same folder (not a package),
# we manually add the folder to sys.path so Python can find it with a plain import.
# This is a common pattern for small scripts that live outside a package.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_client import probe, Sample  # noqa: E402

# --- CONFIGURATION CONSTANTS ---
# Keeping these at the top makes the script easy to reconfigure without
# hunting through the code. "Magic numbers" buried in functions are hard to maintain.
CONTAINER = "uptime-kuma"              # Docker container name to target
DEFAULT_BASE = "http://localhost:3001" # Where Uptime Kuma listens
RESULTS_DIR = "tests/experimental/results"
PROBE_PATH = "/api/entry-page"         # The endpoint we ping to check health
                                       # Chosen because it's fast and always available


# =============================================================================
# PROBE LOOP
# =============================================================================

def probe_loop(url: str, hz: float, stop: threading.Event,
               sink: List[Sample]) -> None:
    """
    Continuously probe `url` at `hz` times per second until `stop` is set.

    --- WHY A SEPARATE THREAD? ---
    We need to SIMULTANEOUSLY:
      (a) inject a fault (e.g. pause Docker for 20 seconds)
      (b) keep measuring HTTP responses the whole time

    Python's threading module lets us do this. The probe_loop runs in a
    background thread while the main thread manages the fault injection.

    --- threading.Event ---
    A threading.Event is a simple on/off flag that is safe to read/write
    from multiple threads at the same time (thread-safe).
    - stop.is_set() returns True once someone calls stop.set()
    - This is the clean way to signal a thread to stop — much better than
      killing it forcefully, which can leave resources in a broken state.

    --- Why append to a shared list? ---
    Lists in Python are thread-safe for append() operations, so the main
    thread can read `sink` after joining the probe thread without any
    locking needed.

    Args:
        url:  The HTTP endpoint to probe
        hz:   Probes per second (5 Hz = 5 probes/sec = one every 200ms)
        stop: Signal flag — loop exits when stop.is_set() is True
        sink: List to append Sample results into (shared with caller)
    """
    interval = 1.0 / hz  # e.g. 1.0 / 5 = 0.2 seconds between probes
    while not stop.is_set():
        sink.append(probe(url))   # probe() returns a Sample(t, status, elapsed_ms, error)
        time.sleep(interval)      # Yield CPU — don't burn 100% just waiting


# =============================================================================
# FAULT IMPLEMENTATIONS
# =============================================================================
# Each fault function takes a duration_s (seconds) and blocks until the
# fault is over. The main thread calls these synchronously while probe_loop
# runs in the background thread.

def fault_pause(duration_s: int) -> None:
    """
    FAULT C1: Freeze the container process using 'docker pause'.

    --- HOW DOCKER PAUSE WORKS ---
    Docker uses Linux's SIGSTOP signal (via cgroups freezer) to suspend ALL
    processes inside the container. The container is still "running" from
    Docker's perspective but no code executes — it's like hitting pause on
    a video. TCP connections that are mid-flight will hang until unpause.

    --- WHAT THIS SIMULATES ---
    Real-world equivalent: a VM being live-migrated, a hypervisor pause
    event, or a garbage collection "stop-the-world" pause in a JVM.
    Also simulates what happens during a host machine sleep/hibernate.

    --- WHY IS MTTR ~0s? ---
    Because unpause is instantaneous — the process resumes exactly where
    it left off with zero restart overhead.
    """
    subprocess.run(["docker", "pause", CONTAINER], check=True, capture_output=True)
    # check=True means subprocess raises CalledProcessError if docker returns non-zero exit code
    # capture_output=True suppresses docker's stdout/stderr from cluttering our output
    time.sleep(duration_s)
    subprocess.run(["docker", "unpause", CONTAINER], check=True, capture_output=True)


def fault_stop_start(duration_s: int) -> None:
    """
    FAULT C2: Fully stop and restart the container.

    --- HOW DOCKER STOP WORKS ---
    'docker stop' sends SIGTERM to PID 1 inside the container, waits up to
    10 seconds for a graceful shutdown, then sends SIGKILL if needed.
    Unlike pause, the process actually exits — all in-memory state is lost.

    --- WHAT THIS SIMULATES ---
    Real-world equivalent: a server crash and reboot, an OOM-killer event,
    a deployment restart, or a pod restart in Kubernetes.

    --- WHY SUBTRACT 2 FROM duration_s? ---
    'docker stop' itself takes ~1-2 seconds to complete (SIGTERM + wait),
    so we sleep for (duration - 2) to keep the total fault window close to
    the intended duration_s.

    --- MTTR MEASURES COLD START TIME ---
    After 'docker start', Node.js needs to:
      1. Start the V8 engine
      2. Load and parse all JavaScript modules
      3. Open the SQLite database
      4. Bind to port 3001
      5. Accept connections
    Our measured MTTR of ~1.01s is the sum of all these steps.
    """
    subprocess.run(["docker", "stop", CONTAINER], check=True, capture_output=True)
    time.sleep(max(duration_s - 2, 1))  # max(..., 1) ensures we never sleep 0 or negative seconds
    subprocess.run(["docker", "start", CONTAINER], check=True, capture_output=True)


def fault_cpu_stress(duration_s: int) -> None:
    """
    FAULT C4: Saturate all CPU cores inside the container.

    --- HOW THE STRESS WORKS ---
    We spawn (nproc * 2) shell busy-loops: 'while :; do :; done'
    The colon ':' is a shell no-op that returns 0 — it's the fastest
    possible instruction, so each loop maxes out one CPU thread.
    Spawning 2x nproc guarantees every logical core hits 100%.

    --- WHY SUBPROCESS.POPEN INSTEAD OF SUBPROCESS.RUN? ---
    subprocess.run() BLOCKS until the command finishes.
    subprocess.Popen() LAUNCHES the command and returns immediately,
    letting our Python code continue (and eventually wait for it to finish).
    This matters here because we want to sleep duration_s while the stress
    is running in the background.

    --- WHAT THIS SIMULATES ---
    Real-world: a runaway process, a crypto-mining attack, a poorly
    optimised batch job, or a traffic spike hitting CPU-heavy code paths
    (e.g. bcrypt password hashing, regex matching, image processing).

    --- KEY FINDING ---
    Uptime Kuma's /api/entry-page endpoint is I/O-bound (it reads from
    SQLite), not CPU-bound. Even with 14/16 cores pegged at 100%, the
    Node.js event loop gets enough CPU slices from Linux's CFS scheduler
    to serve responses in ~3ms. This tells us the bottleneck is disk I/O
    or network, not computation.
    """
    # First find out how many logical CPU cores the container sees
    nproc = int(subprocess.run(["docker", "exec", CONTAINER, "nproc"],
                               capture_output=True, text=True).stdout.strip() or 4)
    # or 4 is a fallback in case nproc returns empty/unexpected output

    workers = nproc * 2  # 2x overcounts to ensure full saturation

    # Build a shell one-liner that spawns `workers` background processes,
    # each running a busy loop for duration_s seconds (via 'timeout')
    cmd = (f"for i in $(seq 1 {workers}); do "
           f"  (timeout {duration_s} sh -c 'while :; do :; done' &) ; "
           f"done; sleep {duration_s + 1}")
    # The final 'sleep' keeps the docker exec process alive until workers finish

    p = subprocess.Popen(
        ["docker", "exec", CONTAINER, "sh", "-c", cmd],
        stdout=subprocess.DEVNULL,   # Discard stdout — we don't need it
        stderr=subprocess.DEVNULL,   # Discard stderr — busy-loops produce none anyway
    )
    try:
        time.sleep(duration_s + 1)   # Wait for stress to complete
    finally:
        # finally block runs even if an exception or KeyboardInterrupt occurs
        # This ensures we always clean up the stress process
        try: p.wait(timeout=2)
        except Exception:
            try: p.kill()            # Force-kill if it didn't exit cleanly
            except Exception: pass   # Ignore errors during cleanup


def fault_latency_proxy(duration_s: int, delay_ms: int = 200) -> None:
    """
    FAULT C3: Inject artificial network latency via a TCP proxy.

    --- HOW THE PROXY WORKS ---
    latency_proxy.py sits between our probe client and Kuma:
        probe -> :3002 (proxy) -> :3001 (Kuma)
    The proxy adds a delay_ms pause before forwarding each chunk of data,
    simulating a slow or geographically distant network link.

    --- WHY NOT USE 'tc' (traffic control)? ---
    Linux's 'tc' command can inject latency at the kernel level, but it
    requires root/CAP_NET_ADMIN privileges which aren't always available.
    A userspace proxy is more portable and requires no special permissions.

    --- WHAT THIS SIMULATES ---
    Real-world: a cross-region API call, a flaky mobile connection,
    an overloaded router, or a saturated WAN link.

    --- WHY DOES OBSERVED LATENCY ≈ 2× delay_ms? ---
    The proxy delays BOTH the request (client→server) and the response
    (server→client), so total round-trip overhead = 2 × 200ms = 400ms.
    This is expected and matches our results (baseline ~5ms → ~401ms).

    --- subprocess.Popen vs run ---
    Again we use Popen (non-blocking) so the proxy runs in the background
    while our probe loop continues measuring through it.
    proc.terminate() sends SIGTERM for graceful shutdown when done.
    """
    cmd = [sys.executable,  # sys.executable = path to the current Python interpreter
           os.path.join(os.path.dirname(__file__), "latency_proxy.py"),
           "--listen", "3002",
           "--upstream", "localhost:3001",
           "--delay-ms", str(delay_ms)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(duration_s)
    finally:
        proc.terminate()              # Graceful shutdown (SIGTERM)
        try: proc.wait(timeout=2)     # Give it 2 seconds to exit cleanly
        except Exception:
            proc.kill()               # Force kill if it ignores SIGTERM


# =============================================================================
# RECOVERY MEASUREMENT
# =============================================================================

def wait_first_2xx(url: str, timeout_s: float = 30.0) -> float | None:
    """
    Poll `url` until we get a 2xx response, returning the elapsed seconds.

    --- WHY THIS MATTERS ---
    This function measures MTTR (Mean Time To Recovery) — one of the most
    important resilience metrics in SRE (Site Reliability Engineering).
    MTTR answers: "After a failure, how long until users can use the service again?"

    Lower MTTR = more resilient system. Industry targets vary:
      - Excellent: < 1 second  (our C2 result: 1.01s ✅)
      - Good:      < 5 seconds
      - Acceptable: < 30 seconds
      - Poor:      > 1 minute

    --- WHY time.perf_counter() INSTEAD OF time.time()? ---
    time.time() returns wall-clock time, which can jump backwards if the
    system clock is adjusted (NTP sync, DST change). perf_counter() is
    a monotonic high-resolution timer that never goes backwards — it's the
    right tool for measuring elapsed time intervals.

    --- POLLING INTERVAL ---
    We poll every 0.25 seconds (250ms). This gives 4 chances per second
    to detect recovery, which is fine-grained enough for our purposes.
    A tighter interval (e.g. 50ms) would give more precise MTTR but wastes
    CPU; a looser interval (e.g. 1s) risks under-measuring fast recoveries.

    Returns:
        float: seconds from start of polling to first 2xx response
        None:  if no 2xx received within timeout_s (system didn't recover)
    """
    start = time.perf_counter()
    deadline = start + timeout_s
    while time.perf_counter() < deadline:
        s = probe(url, timeout_s=1.5)          # Short timeout — we expect fast responses post-recovery
        if 200 <= s.status < 300:              # 2xx = success (200 OK, 204 No Content, etc.)
            return time.perf_counter() - start  # Return elapsed time
        time.sleep(0.25)                        # Wait before next attempt
    return None  # Recovery timed out — system is still down after timeout_s seconds


# =============================================================================
# METRICS SUMMARIZATION
# =============================================================================

def summarize_window(samples: List[Sample], t_start: float, t_end: float) -> dict:
    """
    Calculate availability and latency metrics for a time window.

    --- WHAT IS AVAILABILITY? ---
    Availability = (successful requests / total requests) × 100%
    We count 2xx and 3xx as "ok" (client errors like 404 still mean the
    server is UP and responding). Only connection failures and 5xx count
    as true unavailability.

    --- WHAT IS p95 LATENCY? ---
    p95 (95th percentile) means: "95% of requests were faster than this."
    It's more useful than average because:
    - Average hides outliers (one 10-second request drowns in 999 fast ones)
    - p95 represents what a "real but unlucky" user experiences
    - SLOs (Service Level Objectives) are typically defined on p95/p99

    Example: if p95 = 57ms, then 5% of users waited MORE than 57ms.

    --- WHY NOT USE statistics.quantiles()? ---
    statistics.quantiles() requires Python 3.8+ and is fine, but the
    manual index calculation (int(0.95 * (len-1))) is explicit and works
    the same way. Both give the "nearest rank" percentile.

    Args:
        samples: All probe samples collected during the scenario
        t_start: Unix timestamp marking the start of the window
        t_end:   Unix timestamp marking the end of the window
    """
    # Filter samples to only those within the time window
    win = [s for s in samples if t_start <= s.t < t_end]
    if not win:
        # Return zeroed metrics if no samples fall in this window
        return {"requests": 0, "ok": 0, "errors": 0, "availability_pct": 0,
                "rt_avg_ms": 0, "rt_p95_ms": 0}

    # "ok" = anything that got a response (even 404 means the server is alive)
    ok = [s for s in win if 200 <= s.status < 400]
    errors = [s for s in win if not (200 <= s.status < 400)]  # 5xx, timeouts, connection refused

    durations = [s.elapsed_ms for s in win]
    durations_sorted = sorted(durations)

    # Nearest-rank p95: find the index that represents the 95th percentile
    p95 = durations_sorted[int(0.95 * (len(durations_sorted) - 1))]

    return {
        "requests": len(win),
        "ok": len(ok),
        "errors": len(errors),
        "availability_pct": round(100 * len(ok) / len(win), 2),  # e.g. 96.00
        "rt_avg_ms": round(statistics.fmean(durations), 2),       # fmean = fast mean (C implementation)
        "rt_p95_ms": round(p95, 2),
    }


def write_csv(samples: List[Sample], path: str) -> None:
    """
    Write all probe samples to a CSV file for later analysis.

    --- WHY SAVE RAW DATA? ---
    Computed summaries (averages, percentiles) lose information.
    Raw CSVs let you re-analyse with different time windows, plot graphs
    in Excel/matplotlib, or verify the summary numbers independently.
    This follows the principle: "collect raw data first, summarize second."

    CSV format:
        t           - Unix timestamp (seconds since epoch, 4 decimal places)
        status      - HTTP status code (0 = connection error/timeout)
        elapsed_ms  - Round-trip time in milliseconds
        error       - Error message string, empty if no error
    """
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "status", "elapsed_ms", "error"])  # Header row
        for s in samples:
            w.writerow([round(s.t, 4), s.status, round(s.elapsed_ms, 2), s.error])


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================
# Using a dictionary of scenario configs (instead of if/elif chains) is a
# common pattern called "data-driven programming". Adding a new scenario
# only requires adding a new entry here — the run_scenario() logic is reused.

SCENARIOS = {
    "C1": {
        "name": "API_downtime_pause",
        # WARMUP: 8s baseline — enough probes at 5Hz to establish healthy p95
        "warmup_s": 8,
        # FAULT: 20s pause — long enough to observe steady-state during downtime
        "fault_s": 20,
        # SETTLE: 8s post-recovery — confirms no lingering issues
        "settle_s": 8,
        # lambda wraps the function so it can be called as fault_fn(duration)
        "fault_fn": lambda d: fault_pause(d),
        "url": f"{DEFAULT_BASE}{PROBE_PATH}",
    },
    "C2": {
        "name": "Container_crash_restart",
        "warmup_s": 8,
        "fault_s": 15,   # Shorter than C1 — crash + restart is faster than a long pause
        "settle_s": 12,  # Longer settle — gives time for any warm-up effects to stabilise
        "fault_fn": lambda d: fault_stop_start(d),
        "url": f"{DEFAULT_BASE}{PROBE_PATH}",
    },
    "C3": {
        "name": "Network_latency_200ms",
        "warmup_s": 8,
        "fault_s": 30,   # Long enough to collect meaningful latency statistics
        "settle_s": 8,
        "fault_fn": lambda d: fault_latency_proxy(d, 200),
        # KEY DIFFERENCE: During the fault, probe through the PROXY port (:3002)
        # to actually experience the injected latency. Warmup/settle use direct :3001.
        "url": f"http://localhost:3002{PROBE_PATH}",   # Fault window: through proxy
        "url_warm": f"{DEFAULT_BASE}{PROBE_PATH}",     # Warmup: direct to Kuma
        "url_settle": f"{DEFAULT_BASE}{PROBE_PATH}",   # Settle: direct to Kuma
    },
    "C4": {
        "name": "CPU_stress",
        "warmup_s": 8,
        "fault_s": 30,   # Long enough for the OS scheduler to reach steady state
        "settle_s": 8,
        "fault_fn": lambda d: fault_cpu_stress(d),
        "url": f"{DEFAULT_BASE}{PROBE_PATH}",
    },
}


# =============================================================================
# MAIN SCENARIO RUNNER
# =============================================================================

def run_scenario(sid: str, hz: float = 5.0) -> dict:
    """
    Execute a single chaos scenario and return its summary dict.

    --- THE 4-PHASE PATTERN ---
    Each phase uses its own probe thread + sample list for clean separation.
    This makes it easy to compute metrics per-phase without filtering by time.

    --- WHY hz=5.0 (5 probes per second)? ---
    5 Hz gives us one probe every 200ms — fine-grained enough to detect
    sub-second recovery times (MTTR), but not so fast that we flood the
    server or generate impossibly large CSV files during long scenarios.

    --- THREAD LIFECYCLE ---
    Pattern used in each phase:
        stop = threading.Event()          # Create a new stop signal
        th = threading.Thread(...)        # Create thread (not started yet)
        th.start()                        # Start it — probe_loop begins
        ... do work on main thread ...
        stop.set()                        # Signal the thread to stop
        th.join()                         # Wait for thread to fully exit
                                          # IMPORTANT: never skip join() —
                                          # the thread might still be mid-probe
    """
    s = SCENARIOS[sid]
    print(f"\n[chaos {sid}] {s['name']}")

    # Resolve URLs — C3 uses different URLs per phase, others use the same for all
    url_warm = s.get("url_warm", s["url"])    # dict.get(key, default) — safe fallback
    url_fault = s["url"]
    url_settle = s.get("url_settle", s["url"])

    # ---- PHASE 1: WARMUP ----
    # Establishes a baseline: what does "healthy" look like for this endpoint?
    t0 = time.time()   # Wall-clock start time (used for window filtering later)
    stop = threading.Event()
    samples: List[Sample] = []
    th = threading.Thread(target=probe_loop, args=(url_warm, hz, stop, samples), daemon=True)
    # daemon=True: if main thread crashes, this thread won't keep the process alive
    th.start()
    time.sleep(s["warmup_s"])
    t_warm_end = time.time()
    stop.set(); th.join()  # Clean shutdown of warmup probe thread

    # ---- PHASE 2: FAULT INJECTION ----
    # A NEW probe thread is started so fault samples are in a separate list.
    # Meanwhile the MAIN thread calls fault_fn() which BLOCKS for fault_s seconds.
    # This is the key insight: main thread = fault manager, background thread = probe.
    samples_fault: List[Sample] = []
    stop = threading.Event()
    th = threading.Thread(target=probe_loop, args=(url_fault, hz, stop, samples_fault), daemon=True)
    th.start()
    s["fault_fn"](s["fault_s"])   # BLOCKING: runs the fault for fault_s seconds
    t_fault_end = time.time()
    stop.set(); th.join()

    # ---- PHASE 3: RECOVERY MEASUREMENT ----
    # Measure wall-clock time from fault end to first successful response.
    # This is NOT a probe loop — it's a dedicated recovery detector.
    # We probe url_settle (not url_fault) so C3 measures direct Kuma, not the proxy.
    mttr = wait_first_2xx(url_settle, timeout_s=15.0)
    t_recover = time.time()  # Timestamp when recovery was confirmed (or timed out)

    # ---- PHASE 4: SETTLE ----
    # Confirms the system is fully healthy after recovery. Catches issues like:
    # - Slow memory reclaim after OOM
    # - Connection pool exhaustion after crash
    # - Cache invalidation storms
    samples_settle: List[Sample] = []
    stop = threading.Event()
    th = threading.Thread(target=probe_loop, args=(url_settle, hz, stop, samples_settle), daemon=True)
    th.start()
    time.sleep(s["settle_s"])
    stop.set(); th.join()
    t_settle_end = time.time()

    # ---- COMBINE & SAVE ----
    all_samples = samples + samples_fault + samples_settle
    raw_path = os.path.join(RESULTS_DIR, f"chaos_{sid}_{s['name']}_raw.csv")
    write_csv(all_samples, raw_path)

    # Build the summary — one metrics dict per phase
    summary = {
        "scenario": sid,
        "name": s["name"],
        "warmup":       summarize_window(samples,        t0,          t_warm_end),
        "during_fault": summarize_window(samples_fault,  t_warm_end,  t_fault_end),
        "settle":       summarize_window(samples_settle, t_recover,   t_settle_end),
        # mttr_s: the key resilience number — None means system never recovered in time
        "mttr_s": round(mttr, 2) if mttr is not None else None,
        "raw_csv": raw_path,
    }

    # Quick console summary for live monitoring during the run
    print(f"  warmup avail: {summary['warmup']['availability_pct']}%  "
          f"during fault: {summary['during_fault']['availability_pct']}%  "
          f"settle: {summary['settle']['availability_pct']}%  "
          f"MTTR: {summary['mttr_s']}s")
    return summary


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    """
    Parse CLI arguments and run the requested scenario(s).

    --- WHY argparse? ---
    argparse is Python's standard library for command-line interfaces.
    It automatically generates --help text, validates choices, and handles
    errors gracefully. Much better than manually parsing sys.argv.

    --- RUN ORDER ---
    Scenarios run sequentially (C1 → C2 → C3 → C4), not in parallel.
    Running in parallel would mean faults interfere with each other,
    making results impossible to interpret.
    """
    p = argparse.ArgumentParser()
    # choices= restricts valid values and shows them in --help output
    p.add_argument("--scenario", default="all", choices=["all", "C1", "C2", "C3", "C4"])
    args = p.parse_args()

    # Ensure results directory exists (mkdir -p equivalent)
    os.makedirs(RESULTS_DIR, exist_ok=True)  # exist_ok=True: no error if dir already exists

    keys = ["C1", "C2", "C3", "C4"] if args.scenario == "all" else [args.scenario]
    out = {}
    for k in keys:
        out[k] = run_scenario(k)   # Run each scenario and collect its summary

    # Write combined summary JSON — single file with results from all scenarios
    with open(os.path.join(RESULTS_DIR, "chaos_summary.json"), "w") as f:
        json.dump(out, f, indent=2)  # indent=2 makes it human-readable

    print(f"\n[done] -> {os.path.join(RESULTS_DIR, 'chaos_summary.json')}")


if __name__ == "__main__":
    # This guard means: only run main() if this file is executed directly.
    # If another script imports run_chaos.py, main() won't auto-execute.
    # This is a Python best practice for all executable scripts.
    main()
