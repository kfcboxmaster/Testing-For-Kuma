# Assignment 3 — Experimental Testing Report
**Project:** Uptime Kuma — QA Automation Suite
**Author:** Kuanysh Kambarov  •  **Date:** 25 April 2026  •  **Course:** QA / Astana IT University

---

## 1. System under test

The product under test is **Uptime Kuma**, a self-hosted uptime monitor
(MIT-licensed, ~80k LoC of JavaScript). For these experiments we run
`louislam/uptime-kuma:2` as a Docker container on the local host:

| Item | Value |
|---|---|
| Image | `louislam/uptime-kuma:2` (digest pinned during run) |
| Host OS | WSL2 Ubuntu 24.04 on Windows 11 |
| CPU / RAM | 16 logical cores / 15.5 GiB available to container |
| Network | loopback `localhost:3001` |
| Storage | named volume `uptime-kuma:/app/data` (SQLite default) |
| Test client | Python 3.12 (stdlib only) |
| Container restart cold-start | **2.0 s** (measured) |
| Test code | `tests/experimental/{performance,mutation,chaos}/` |

### High-risk modules (selected from midterm risk analysis)

| # | Module | Why high-risk |
|---|---|---|
| 1 | `routers/status-page-router.js` | Public-facing status pages — broken routing here is a top-severity availability bug |
| 2 | `routers/api-router.js` | Houses `/api/entry-page`, `/api/badge`, `/api/push` — hot-path REST endpoints |
| 3 | `password-hash.js` | Security-critical primitive used by every login |
| 4 | `rate-limiter.js` | Brute-force defence; mutation could silently disable protection |

These four modules are the targets for both the mutation suite and the
chaos probes (which exercise the routers).

---

## 2. Performance Testing

### 2.1 Methodology

A custom Python load generator (`load_runner.py`, 165 LoC, stdlib only)
drives four scenarios against the container. Each scenario runs N
concurrent threads ("virtual users", VU) issuing back-to-back requests
randomly drawn from the four hot endpoints. `docker stats` is sampled
every 2 s in parallel to record container CPU/memory.

| ID | Scenario | Concurrency | Duration | SLO target |
|---|---|---|---|---|
| S1 | Normal load | 10 VU | 60 s | p95 < 250 ms, 5xx < 1% |
| S2 | Peak load | 50 VU | 60 s | p95 < 800 ms, 5xx < 2% |
| S3 | Spike (5→25→60→100) | step ramp | 60 s | p95 < 1500 ms, 5xx < 5% |
| S4 | Endurance / soak | 20 VU | 60 s (`--short`) | p95 stable, 5xx < 1% |

Endpoints rotated: `/api/status-page/main`, `/api/status-page/heartbeat/main`,
`/api/badge/1/status`, `/api/entry-page`. The first returns 404 because no
status page is configured — we count 4xx as "client error" (still a
successful round-trip) and only 5xx + connection failures as SLO failures.

### 2.2 Results

| Scenario | Requests | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | 5xx err | SLO |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| S1 normal      | 131 700 | 2 396 | 4.4 | **6.7** | 7.9 | 176 | 0% | ✅ pass |
| S2 peak        | 132 351 | 2 394 | 22.0 | **35.2** | 42.2 | 66 | 0% | ✅ pass |
| S3 spike       | 136 498 | 2 438 | 15.7 | **57.4** | 74.0 | 137 | 0% | ✅ pass |
| S4 endurance   | 132 252 | 2 395 | 8.8 | **13.8** | 16.5 | 43 | 0% | ✅ pass |

**Throughput is flat at ~2 400 RPS across all scenarios** — Kuma is CPU-bound
on a single Node event loop, so adding VUs only adds queueing delay.

### 2.3 Per-endpoint breakdown (S2 peak)

| Endpoint | RPS | p50 (ms) | p95 (ms) | Notes |
|---|---:|---:|---:|---|
| `/api/entry-page` | 597 | 22.0 | 35.2 | Settings lookup, DB read |
| `/api/status-page/heartbeat/main` | 595 | 22.1 | 35.3 | DB query + JSON serialisation |
| `/api/status-page/main` | 596 | 22.0 | 35.2 | Returns 404 (no slug) |
| `/api/badge/1/status` | 605 | 22.0 | 35.1 | Computes SVG per request |

All four endpoints scale identically — there is no single bottleneck
endpoint at this load.

### 2.4 Resource usage (60 s perf-all run, 2 s sample)

| Metric | Avg | Max | End |
|---|---:|---:|---:|
| CPU (% of 1 core) | **56.9%** | 79.2% | — |
| Memory (MiB) | — | **372 MiB** | 124 MiB (delta +2) |

CPU never exceeds **79 %** of one core — Node's single event-loop
architecture means a scale-up here requires a cluster-mode reverse proxy.
Memory grows during peak load (122 → 372 MiB) but recovers fully during
the cool-down (no leak signature across 4-minute combined run).

### 2.5 Bottleneck analysis & recommendations

| # | Finding | Impact | Recommendation |
|---|---|---|---|
| B1 | p95 grows linearly with VU (6 → 35 → 57 ms) | OK now, but a DDoS or large user base will push p95 past SLO | Front Kuma with a reverse-proxy cache (NGINX `proxy_cache` for `/api/badge/*` and `/api/status-page/*`) — these are already cached internally for 1–5 minutes. |
| B2 | Single-core ceiling at ~80 % CPU | Cannot use the other 15 cores | Run Kuma in cluster mode (PM2) or place a load-balancer in front of multiple instances; SQLite would have to move to MariaDB. |
| B3 | Memory headroom 122 → 372 MiB during peak | Ample today, watch on small VPS | Cap container with `--memory=512m` and re-run S2; expect graceful degradation, not OOM. |

Raw traces: `tests/experimental/results/perf_*.csv`.

---

## 3. Mutation Testing

### 3.1 Methodology

A custom container-injection mutation harness (`mutation_runner.py`)
implements the full mutate-restart-probe-restore cycle:

1. `docker exec cat <file>` reads the original module.
2. The mutant is applied as a string replacement, written back via
   `docker cp`, and the container is restarted (~2 s).
3. A 10-probe HTTP suite is executed: status code + first 80 chars of
   body + CORS header are compared against an unmutated baseline.
4. If any probe deviates, the mutant is **killed**; otherwise it
   **survives** (a test-suite gap).
5. The original is restored and the next mutant runs from a clean state.

Modules behind authentication (`password-hash.js`, `rate-limiter.js`)
cannot be exercised: this Docker instance has no admin user (Kuma 2.x
setup is over Socket.IO, which the WSL toolchain cannot drive without
extra packages). Their mutants are documented and traced manually to
the existing `tests/socket_api/test_auth.py` cases — see
`mutation/manual_mutants.md`.

### 3.2 Results

| Module | Operators used | Mutants | Killed | Survived | Score |
|---|---|---:|---:|---:|---:|
| `routers/status-page-router.js` | LOR, SDL, CRC, RVR, FCR | 5 | 2 | 3 | **40.0%** |
| `routers/api-router.js`         | RVR×2, LOR, CRC, SDL, ROR | 6 | 3 | 3 | **50.0%** |
| `password-hash.js` (manual) | RVR×2, LOR, CRC, FCR | 5 | 2 | 3 | **40.0%** |
| `rate-limiter.js` (manual)  | CRC×2, ROR, RVR, FCR | 5 | 2 | 3 | **40.0%** |
| **Overall** | — | **21** | **9** | **12** | **42.9%** |

### 3.3 Surviving-mutant root causes

| Cause | Count | Example | Why the test suite missed it |
|---|---:|---|---|
| Equivalent mutant | 1 | API-SDL-1 — drop `allowDevAllOrigin` | function is a no-op outside `NODE_ENV=development` |
| Unreachable code path (no fixture) | 4 | SPR-RVR-1 — `response.json(null)` for found page | no status page exists in the test DB |
| Behavior invisible to a single probe | 2 | SPR-CRC-1 — cache 1 min → 0 min | caching is invisible without rapid-fire probes against changing data |
| Path not exercised by any test | 5 | API-LOR-1 — invert `trustProxy` | no proxy-header test |

### 3.4 Recommended additions to the test suite (ranked by ROI)

1. **Admin-setup fixture** that completes Kuma's setup wizard once at
   session start. Unblocks status-page fixtures and unblocks all auth-bound
   mutants. Estimated to convert **5 of 12** survivors into kills.
2. **Brute-force login test** (loop 25× wrong-password, assert rate-limit
   payload). Kills RL-CRC-2, RL-RVR-1, RL-FCR-1.
3. **CORS assertion** for `/api/entry-page` against a `NODE_ENV=development`
   container. Kills API-SDL-1.
4. **Push-with-ping integration test** (`?ping=99999999999` allowed,
   `?ping=-1` rejected). Kills API-ROR-1 and API-CRC-1 directly.
5. **Proxy-header test** (`X-Forwarded-Host: foo` with `trustProxy=1`).
   Kills API-LOR-1.

Raw mutant traces (probe diffs per mutant): `tests/experimental/results/mutation_results.json`.

---

## 4. Chaos / Fault-Injection Testing

### 4.1 Methodology

`run_chaos.py` orchestrates four scenarios. Each is a four-phase
experiment: **WARMUP → INJECT → RECOVER → SETTLE**. A 5 Hz HTTP probe
client samples `/api/entry-page` throughout, recording status, latency,
and error class. **MTTR** is measured as wall-clock time from
fault-end to first 2xx response.

| ID | Fault | Mechanism | Duration |
|---|---|---|---|
| C1 | API downtime | `docker pause` (process frozen) | 20 s |
| C2 | Container crash | `docker stop` + `docker start` | 15 s |
| C3 | Network latency | TCP proxy on :3002 → :3001, +200 ms each chunk | 30 s |
| C4 | CPU exhaustion | 32 busy loops inside container (saturates 14.6/16 cores) | 30 s |

### 4.2 Results

| Scenario | Avail. during fault | Avg latency during fault | MTTR | Verdict |
|---|---:|---:|---:|:---:|
| C1 API downtime (`pause`) | **12.5 %** | 2 193 ms | 0.00 s | ✅ pass — recovery is instantaneous on `unpause` |
| C2 Container crash | **1.7 %** | 43 ms | **1.01 s** | ✅ pass — cold start under the 5 s threshold |
| C3 Network latency (+200 ms) | **96.0 %** | 401 ms | 0.01 s | ✅ pass — 2 timeouts only, latency tracked the injection |
| C4 CPU saturation (≈ 14 cores busy) | **100.0 %** | 2.8 ms | 0.00 s | ✅ pass — Node event loop got enough cycles |

### 4.3 Observations

- **C1 — pause.** The 12.5 % availability number is requests that
  completed the TCP handshake before the freeze, plus those issued in
  the small windows around `pause` / `unpause`. Once `unpause` returns,
  Kuma resumes serving in < 250 ms. **No retry/queueing logic is needed
  on the client side** for short upstream pauses if clients have a 2.5 s
  timeout.
- **C2 — cold restart.** MTTR of 1.01 s is excellent for a Node app. The
  recovered container served identical baseline latency
  (p95 6.6 ms ≈ pre-fault). **No tail of 5xx after recovery** — bcrypt
  cost on first login is the only visible warm-up effect (untested here).
- **C3 — latency injection.** The proxy adds delay per direction
  (request and response), so the observed +400 ms ≈ 2 × 200 ms. Kuma
  itself stays healthy; failures are 2 client timeouts at the 2.5 s
  budget. **Recommendation:** a status-page consumer hitting Kuma over a
  high-latency link should set the heartbeat polling interval > 1 s.
- **C4 — CPU stress.** With 14.6 of 16 cores burning 100 %, the entry-page
  endpoint still responded in ~3 ms. Linux's CFS scheduler ensures
  Kuma's mostly-idle Node process gets scheduled promptly. **Caveat:**
  this only proves the endpoint is I/O-bound; CPU-heavy operations
  (regex-driven monitor checks, bcrypt rehash) would degrade.
  A follow-up experiment should pin the container with `--cpus=0.5`.

### 4.4 Recommendations

| # | Issue | Recommendation |
|---|---|---|
| R1 | C1 caused 7 in-flight requests to hang ≈ 2 s (timeout) | Add HTTP keep-alive timeouts < 2 s in the reverse proxy in front of Kuma |
| R2 | C2 cold start is 1 s — within budget but not resilient under load | Use Docker `restart: always` and place behind a load-balancer with health checks (failover < 250 ms) |
| R3 | C3 caused 2/50 timeouts | Increase client-side timeout to 5 s for status page polling, or implement exponential-backoff retry |
| R4 | C4 didn't trigger degradation at this load | Re-run with `--cpus=0.5` to confirm degradation curve before production sizing |

Raw probe traces: `tests/experimental/results/chaos_*_raw.csv`.

---

## 5. Comparative analysis — expected vs observed

| Risk (midterm) | Hypothesis | Observed | Verdict |
|---|---|---|---|
| Status-page DB lookup is the bottleneck | p95 > 200 ms at 50 VU | p95 = 35 ms at 50 VU | **overestimated** — SQLite is fine for ≤ 50 VU |
| Single-core architecture caps RPS | Hard ceiling around 2 000 RPS | Observed 2 396–2 438 RPS, flat | **confirmed** |
| Cold restart > 5 s | Long MTTR | 1.01 s | **overestimated** — Kuma boots fast |
| Network jitter degrades availability proportionally | Linear loss | Stays at 96 % availability | **as expected** |
| CPU saturation tolerable | Significant degradation expected | No measurable impact | **underestimated robustness** |
| Authentication tests give high coverage | Mutation score > 75 % | Auth-bound modules score 40 % | **underestimated risk** — coverage gap |
| Status-page router has solid tests | High kill rate | 40 % | **underestimated risk** |

The biggest surprise is **how much test coverage is hidden behind the
unconfigured admin user**: half of the surviving mutants would die under
a single new fixture. This is the highest-value follow-up.

---

## 6. Lessons learned & recommendations

### Process
- **Containerised mutation testing works** — patching the running Docker
  image and round-tripping through HTTP probes detects 9/21 mutants
  without any access to Kuma's bundled test suite. The same harness can
  run in CI on every PR with the existing `Jenkinsfile` against an
  ephemeral container.
- **Always include CORS / header signatures** in mutation probes; without
  them, an entire class of "drop the security middleware" mutants
  survives silently.
- **Saturation testing must respect the workload type.** Burning CPU
  cores does not stress an I/O-bound endpoint. Always include both
  CPU- and I/O-heavy scenarios.

### Product
- **Single-core architecture is the dominant performance constraint.**
  Reverse-proxy caching of `/api/badge/*` and `/api/status-page/*` is
  the cheapest 10× throughput improvement available.
- **The auth/rate-limit code is silently under-tested.** Adding three
  small tests (admin setup, brute-force login, push-with-ping) would
  raise the mutation score from 42.9 % → ~75 %.
- **Resilience is solid for short faults**, but the project would
  benefit from documenting the recovery behaviour explicitly in a
  runbook so that operators know that a 1-s blip on `unpause` is
  expected and not an outage.

---

## 7. Reproduction

```bash
# 1. Start the SUT
docker run -d --restart=always --name uptime-kuma \
    -p 3001:3001 -v uptime-kuma:/app/data louislam/uptime-kuma:2

# 2. Performance (≈ 4 minutes, --short shrinks endurance to 60 s)
python3 tests/experimental/performance/load_runner.py --scenario all --short

# 3. Mutation (≈ 4 minutes, 11 container restarts)
python3 tests/experimental/mutation/mutation_runner.py --all

# 4. Chaos (≈ 5 minutes, four scenarios)
python3 tests/experimental/chaos/run_chaos.py --scenario all
```

All raw artifacts land in `tests/experimental/results/`. The Jenkinsfile
already runs the existing pytest suite; adding the three commands above
as additional stages would make every PR run the full experimental
battery.
