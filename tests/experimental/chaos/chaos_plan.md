# Chaos / Fault-Injection Plan — Uptime Kuma

## Goal
Quantify Kuma's resilience by injecting representative faults into the
running container while a steady client probes a public endpoint, and measure:

- **Availability (%)** during the fault
- **Mean Time To Recover (MTTR)** — wall time from fault end to first 2xx
- **Error propagation** — which probes fail vs. degrade gracefully
- **Service degradation** — increase in latency under stress

## Faults
| ID | Fault type | Mechanism | Duration |
|---|---|---|---|
| C1 | API downtime | `docker pause` / `docker unpause` (process frozen, port still open) | 20 s |
| C2 | Container crash | `docker stop` then `docker start` (cold restart) | 15 s |
| C3 | Network latency | TCP proxy on :3002 → :3001 with 200 ms injected delay | 30 s |
| C4 | CPU exhaustion | `docker exec ... yes > /dev/null` x N to saturate the CPU pinned to the container | 30 s |

## Probe
A small client (`probe_client.py`) sends 2 requests/second to
`/api/entry-page` for the duration of the experiment, recording:
`(timestamp, status, elapsed_ms, error)`.

## Pass / fail thresholds
| Fault | Acceptable behavior |
|---|---|
| C1 pause | 100% errors during pause; first request after `unpause` returns 200 within 2 s |
| C2 crash | 100% errors during stop; cold start ≤ 5 s; no tail of 5xx after recovery |
| C3 latency | latency uniformly increases by ≈ 200 ms; error rate ≤ 1 % |
| C4 CPU stress | error rate ≤ 5 %; p95 latency increases but stays < 2 s; no crash |

## Tooling
- Plain `docker` CLI on the host (already used for the deployment)
- `tests/experimental/chaos/latency_proxy.py` — stdlib TCP proxy with
  configurable delay
- `tests/experimental/chaos/probe_client.py` — stdlib HTTP probe driver
- `tests/experimental/chaos/run_chaos.py` — orchestrates the four scenarios,
  emits CSVs and a per-scenario JSON summary
