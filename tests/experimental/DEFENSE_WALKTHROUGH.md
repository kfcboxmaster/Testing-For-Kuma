# Defense Walkthrough — Assignment 3

A linear, copy-pasteable script for the live demo. Each step says **what to
say, what to run, what to point at**. Total run time end-to-end is ~13 minutes;
the walkthrough below skips the long endurance test so the live demo finishes
in **~6 minutes**.

---

## 0. Prerequisites (do this BEFORE the defense starts)

On the demo machine:

```bash
# clone the repo
git clone <repo-url> kuma_automation
cd kuma_automation

# verify Python 3.10+ and Docker
python3 --version
docker --version
```

Required:
- **Docker** (running)
- **Python 3.10+** — stdlib only, no `pip install` needed
- **Bash** (for `sample_resources.sh` — Git Bash works on Windows)
- Ports **3001** and **3002** free

Pull the Kuma image once so the demo isn't spent on a download:

```bash
docker pull louislam/uptime-kuma:2
```

---

## 1. Start Uptime Kuma (the System Under Test) — 30 s

> **Say:** "Our SUT is Uptime Kuma running in Docker so the environment is
> reproducible across machines."

```bash
docker rm -f uptime-kuma 2>/dev/null
docker run -d --restart=always --name uptime-kuma \
    -p 3001:3001 -v uptime-kuma:/app/data louislam/uptime-kuma:2

# wait until it answers
until curl -sf http://localhost:3001/api/entry-page >/dev/null; do sleep 1; done
echo "Kuma is up."
```

> **Point at:** `docker ps` — the `Up X seconds (healthy)` status confirms it
> is running.

---

## 2. Open the report (have it ready in a tab) — 30 s

> **Say:** "All numbers I'm about to reproduce live are in this report.
> The headline metrics are in section 7."

```bash
# pick whichever you have available
code tests/experimental/report/experimental_testing_report.md   # VS Code
# or
less tests/experimental/report/experimental_testing_report.md
```

> **Point at:** Section 1 (system under test) and the headline tables.

---

## 3. Performance testing — ~3 minutes

> **Say:** "We have four scenarios — normal, peak, spike, endurance — driven
> by a stdlib Python load generator. No external tools needed. We sample
> CPU/memory in parallel."

Open **two terminals** side by side.

### Terminal A — resource sampler
```bash
tests/experimental/performance/sample_resources.sh 200 \
    tests/experimental/results/perf_demo_resources.csv
```

### Terminal B — load runner
```bash
python3 tests/experimental/performance/load_runner.py \
    --scenario all --short \
    --base-url http://localhost:3001 \
    --out tests/experimental/results
```

> **While it runs, say:** "Each VU is a Python thread issuing back-to-back
> requests across four endpoints — entry-page, badge, status-page,
> heartbeat. We measure p50/p95/p99 latency and we count only 5xx +
> connection errors as SLO failures because 4xx is a valid handled response."

When it finishes (you'll see four `[run]` blocks):

```bash
python3 -c "
import json
d = json.load(open('tests/experimental/results/perf_summary.json'))
print(f\"{'scenario':14s} {'rps':>8} {'p50':>6} {'p95':>6} {'p99':>6} {'5xx%':>6}\")
for k,v in d.items():
    s = v['summary']
    print(f\"{k:14s} {s['rps']:>8} {s['rt_median_ms']:>6} {s['rt_p95_ms']:>6} {s['rt_p99_ms']:>6} {s['error_rate_pct']:>6}\")
"
```

> **Point at:**
> - **Throughput is flat at ~2 400 RPS** — the single Node event loop is
>   the bottleneck.
> - **p95 grows linearly with concurrency** (6 → 35 → 57 ms) — predictable.
> - **0 % 5xx everywhere** — Kuma never crashes under this load.

```bash
# resource summary
python3 -c "
import csv, statistics
rows = list(csv.DictReader(open('tests/experimental/results/perf_demo_resources.csv')))
cpu = [float(r['cpu_pct']) for r in rows if r['cpu_pct']]
mem = [float(r['mem_mib']) for r in rows if r['mem_mib']]
print(f'CPU% avg={statistics.fmean(cpu):.1f}  max={max(cpu):.1f}')
print(f'Mem MiB start={mem[0]:.0f} max={max(mem):.0f} end={mem[-1]:.0f}')
"
```

> **Say:** "CPU never exceeds ~80 % of one core. Memory grows during peak
> load and is fully released afterwards — no leak signature."

---

## 4. Mutation testing — ~4 minutes

> **Say:** "Stryker would be the standard tool but it needs the project's
> Node test suite, which we can't run from here. So we built a custom
> harness that patches the running container, restarts Kuma, and probes via
> HTTP. A mutant is killed if any probe deviates from baseline."

### 4a. Show one mutant first (to make the mechanism visible)

```bash
python3 tests/experimental/mutation/mutation_runner.py --id SPR-LOR-1
```

> **Point at:** the `[mutant SPR-LOR-1]` line — the mutation is "negate the
> not-found branch". When the harness reports `killed=1/1`, open the JSON
> to show **why** it was killed:

```bash
python3 -c "
import json; m = json.load(open('tests/experimental/results/mutation_results.json'))['mutants'][0]
print('killed:', m['killed'])
print('diffs:', m['probe_diffs'])
"
```

> **Say:** "Probe P3 — `/api/status-page/main` — returned 403 instead of 404.
> That's how we detect the mutant: the existing test suite would catch
> this regression."

### 4b. Run the full automated suite

```bash
python3 tests/experimental/mutation/mutation_runner.py --all 2>&1 \
    | grep -E "^\[(mutant|summary)"
```

When done (~3 min):

```bash
python3 -c "
import json
d = json.load(open('tests/experimental/results/mutation_results.json'))
killed = sum(1 for m in d['mutants'] if m['killed'])
total  = len(d['mutants'])
print(f'killed {killed}/{total} = {killed/total*100:.1f}% mutation score')
for m in d['mutants']:
    mt = m['mutant']; tag = 'KILL' if m['killed'] else 'SURV'
    print(f'  [{tag}] {mt[\"id\"]:12s} {mt[\"description\"][:60]}')
"
```

> **Say:** "We get 5 of 11 automated mutants killed — that plus 4 manual
> mutants on the auth-bound modules brings us to **42.9 % mutation score on
> 21 mutants total**." Open `mutation/summary.md` to show the
> ROI-ranked list of test additions.

```bash
cat tests/experimental/mutation/summary.md | head -50
```

> **Point at:** the "Surviving mutants — root-cause categories" table.
> "These aren't bugs in the test suite logic — they're observable test
> coverage gaps."

---

## 5. Chaos / fault-injection — ~5 minutes

> **Say:** "Four faults: API pause, container crash, network latency,
> CPU saturation. A 5 Hz HTTP probe runs throughout. We measure
> availability during the fault and MTTR after it."

```bash
python3 tests/experimental/chaos/run_chaos.py --scenario all 2>&1 | tail -15
```

When done:

```bash
python3 -c "
import json
d = json.load(open('tests/experimental/results/chaos_summary.json'))
print(f\"{'scenario':32s} {'avail %':>7} {'avg ms':>8} {'MTTR s':>7}\")
for k,v in d.items():
    f = v['during_fault']
    print(f\"{k+' '+v['name']:32s} {f['availability_pct']:>7} {f['rt_avg_ms']:>8} {str(v['mttr_s']):>7}\")
"
```

> **Point at each row:**
> - **C1 pause:** 12 % availability is correct — the process is frozen.
>   On `unpause` Kuma resumes serving instantly (MTTR ~0 s).
> - **C2 crash + restart:** **MTTR = 1.01 s** — well under our 5 s target.
> - **C3 +200 ms latency:** 96 % availability with 2 timeouts.
> - **C4 CPU saturation:** **100 % availability** — Linux's CFS scheduler
>   keeps Kuma's mostly-idle event loop responsive even with 14/16 cores
>   pegged. Caveat in the report: an I/O-bound endpoint, so this only
>   proves robustness for that workload.

```bash
# show the proxy + crash details if asked
ls tests/experimental/results/chaos_*_raw.csv
```

---

## 6. Comparative analysis — 1 minute

> **Say:** "The most interesting finding is in section 5 of the report —
> what we got right vs wrong from the midterm risk analysis."

```bash
sed -n '/## 5. Comparative analysis/,/## 6/p' \
    tests/experimental/report/experimental_testing_report.md
```

> **Highlights:**
> - We **overestimated** the cost of the SQLite DB lookups.
> - We **underestimated** the size of the auth-test gap.
> - We **confirmed** the single-core RPS ceiling.

---

## 7. Cleanup

```bash
docker stop uptime-kuma && docker rm uptime-kuma
docker volume rm uptime-kuma  # only if you want a clean state
```

---

## If something fails live

| Symptom | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Start Docker Desktop / `sudo systemctl start docker` |
| `port is already allocated` | `docker rm -f uptime-kuma` and try again |
| `python3: command not found` | Use `python` on Windows; on Linux install `python3` |
| `bc: command not found` (resource sampler only) | Skip the sampler step — runner still produces full perf metrics |
| Mutation harness hangs after restart | Container failed to come back up — `docker logs uptime-kuma`, then run with `--id <one-id>` to isolate |
| Chaos C3 reports connection-refused | Port 3002 is taken — `lsof -i :3002` and kill the holder |

---

## Speaker notes — one-liner per section

| Section | Hook |
|---|---|
| Performance | "Throughput plateaus at 2 400 RPS — Kuma is single-core bound." |
| Mutation | "We patch the running container, restart, probe — 42.9 % score, five named test additions raise it to ~75 %." |
| Chaos | "MTTR is 1 second on cold restart and CPU saturation didn't move the needle — that's robustness." |
| Comparative | "Three of our seven midterm risk hypotheses were wrong — that's the value of doing this." |
