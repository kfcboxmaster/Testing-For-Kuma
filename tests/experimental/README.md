# Assignment 3 — Experimental Engineering

Performance, mutation, and chaos testing for Uptime Kuma.

## Where things live

| Path | What |
|---|---|
| `report/experimental_testing_report.md` | **The report (4–6 pages).** Read this first. |
| `performance/test_plan.md` | Scenarios, SLOs, test-design rationale |
| `performance/load_runner.py` | stdlib Python load generator (S1–S4) |
| `performance/sample_resources.py` | docker-stats sampler (CPU / memory) — pure Python, works on Windows |
| `performance/sample_resources.sh` | bash equivalent (Linux/macOS/Git Bash) |
| `mutation/mutation_plan.md` | Mutation methodology + module list |
| `mutation/mutation_runner.py` | Container-injection mutation harness |
| `mutation/manual_mutants.md` | Static analysis for auth-bound modules |
| `mutation/summary.md` | Combined mutation results & ROI ranking |
| `chaos/chaos_plan.md` | Fault types, durations, pass/fail thresholds |
| `chaos/run_chaos.py` | C1–C4 orchestrator |
| `chaos/probe_client.py` | 5 Hz HTTP probe used by chaos scenarios |
| `chaos/latency_proxy.py` | TCP proxy with configurable delay (used by C3) |
| `results/` | All CSV / JSON output from the runs above |
| `mock_kuma.py` | Local stand-in (unused once the Docker SUT was available) |

## Run everything from scratch

Prereqs: Docker + Python 3.10+. No `pip` packages required.
Works natively on **Linux**, **macOS**, and **Windows** (with Docker Desktop) — no WSL needed.

```bash
docker run -d --restart=always --name uptime-kuma \
    -p 3001:3001 -v uptime-kuma:/app/data louislam/uptime-kuma:2
sleep 5
python3 tests/experimental/performance/load_runner.py --scenario all --short
python3 tests/experimental/mutation/mutation_runner.py --all
python3 tests/experimental/chaos/run_chaos.py --scenario all
```

Total runtime: ~13 minutes. All artifacts written to `tests/experimental/results/`.

## Headline numbers (run on 2026-04-25)

| Block | Headline |
|---|---|
| Performance | 2 396–2 438 RPS sustained, p95 = 6.7 ms (S1) → 57 ms (S3 spike), 0% 5xx |
| Mutation | **42.9 %** mutation score (9/21 killed). Five named test additions raise this to ≈ 75 %. |
| Chaos | 100 % availability under CPU saturation; **MTTR = 1.01 s** on cold restart; 96 % availability with +200 ms network latency. |
