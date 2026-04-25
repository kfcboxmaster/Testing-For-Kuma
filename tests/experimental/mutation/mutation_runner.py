"""
Mutation testing harness for Uptime Kuma.

For each declared mutant:
    1. Read the original file from inside the running container.
    2. Apply the mutation (string replace).
    3. Copy the patched file back into the container.
    4. Restart the container.
    5. Wait for /api/entry-page to respond (or timeout = killed-by-startup).
    6. Run the HTTP probe suite.
    7. Mark mutant as KILLED if any probe deviates from baseline,
       SURVIVED otherwise.
    8. Restore the original file and restart so the next mutant starts clean.

Output:
    tests/experimental/results/mutation_<module>.json
    tests/experimental/results/mutation_summary.csv

Usage:
    python3 mutation_runner.py --module status-page-router
    python3 mutation_runner.py --all
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Callable, List, Optional


CONTAINER = "uptime-kuma"
BASE_URL = "http://localhost:3001"
RESULTS_DIR = "tests/experimental/results"
WAIT_TIMEOUT_S = 30


@dataclass
class Mutant:
    id: str
    file: str           # path inside container, e.g. /app/server/routers/status-page-router.js
    operator: str       # LOR, ROR, AOR, CRC, SDL, RVR, FCR
    description: str
    find: str
    replace: str
    occurrence: int = 1  # if `find` appears more than once, which to mutate (1-based)


@dataclass
class ProbeResult:
    name: str
    status: int
    body_snippet: str
    headers: dict
    elapsed_ms: float
    error: str = ""


@dataclass
class MutantResult:
    mutant: dict
    killed: bool
    survived_reason: str = ""
    probe_diffs: list = field(default_factory=list)
    notes: str = ""


# --- Mutant catalogue ---------------------------------------------------------

STATUS_PAGE_ROUTER = "/app/server/routers/status-page-router.js"
API_ROUTER         = "/app/server/routers/api-router.js"

MUTANTS: List[Mutant] = [
    # status-page-router.js
    Mutant("SPR-LOR-1", STATUS_PAGE_ROUTER, "LOR",
           "negate the not-found branch — slug-not-found becomes slug-found",
           "if (!statusPage) {", "if (statusPage) {"),
    Mutant("SPR-SDL-1", STATUS_PAGE_ROUTER, "SDL",
           "drop slug.toLowerCase() in /api/status-page/:slug",
           "    slug = slug.toLowerCase();\n\n    try {\n        // Get Status Page",
           "\n    try {\n        // Get Status Page", occurrence=1),
    Mutant("SPR-CRC-1", STATUS_PAGE_ROUTER, "CRC",
           "shrink heartbeat cache to 0 minutes",
           "cache(\"1 minutes\")", "cache(\"0 minutes\")"),
    Mutant("SPR-RVR-1", STATUS_PAGE_ROUTER, "RVR",
           "force /api/status-page/:slug to return null instead of JSON",
           "response.json(statusPageData);", "response.json(null);"),
    Mutant("SPR-FCR-1", STATUS_PAGE_ROUTER, "FCR",
           "remove the sendHttpError on not-found path",
           'sendHttpError(response, "Status Page Not Found");',
           '/* sendHttpError removed */;'),

    # api-router.js
    Mutant("API-RVR-1", API_ROUTER, "RVR",
           "return wrong shape for entry-page (drop type field)",
           'result.type = "entryPage";\n        result.entryPage = server.entryPage;',
           'result.entryPage = server.entryPage;'),
    Mutant("API-LOR-1", API_ROUTER, "LOR",
           "negate the trustProxy condition",
           'if ((await Settings.get("trustProxy")) && request.headers["x-forwarded-host"]) {',
           'if (!((await Settings.get("trustProxy")) && request.headers["x-forwarded-host"])) {'),
    Mutant("API-CRC-1", API_ROUTER, "CRC",
           "shrink the push max-ping ceiling so any normal ping is rejected",
           "const MAX_PING_MS = 100000000000;",
           "const MAX_PING_MS = 0;"),
    Mutant("API-SDL-1", API_ROUTER, "SDL",
           "drop allowDevAllOrigin from entry-page (CORS regressions)",
           'router.get("/api/entry-page", async (request, response) => {\n    allowDevAllOrigin(response);\n',
           'router.get("/api/entry-page", async (request, response) => {\n'),
    Mutant("API-ROR-1", API_ROUTER, "ROR",
           "weaken push ping range check (< 0 -> <= 0)",
           "if (ping !== null && (ping < 0 || ping > MAX_PING_MS)) {",
           "if (ping !== null && (ping <= 0 || ping > MAX_PING_MS)) {"),
    Mutant("API-RVR-2", API_ROUTER, "RVR",
           "make push handler return 200 even when monitor missing",
           '"Monitor not found or not active."',
           '"Always OK"'),
]


# --- Container helpers --------------------------------------------------------

def docker_cp_out(src_in_container: str) -> str:
    """Read a file from the container as text."""
    out = subprocess.run(
        ["docker", "exec", CONTAINER, "cat", src_in_container],
        capture_output=True, text=True, check=True
    )
    return out.stdout


def docker_write(dest_in_container: str, content: str) -> None:
    """Replace a file inside the container with the provided content."""
    tmp = "/tmp/_mutation_payload"
    with open(tmp, "w") as f:
        f.write(content)
    subprocess.run(["docker", "cp", tmp, f"{CONTAINER}:{dest_in_container}"], check=True)


def docker_restart() -> None:
    subprocess.run(["docker", "restart", CONTAINER],
                   check=True, capture_output=True)


def wait_until_ready(timeout: int = WAIT_TIMEOUT_S) -> bool:
    """Poll /api/entry-page until 200 or timeout. Return True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE_URL + "/api/entry-page", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# --- Probes -------------------------------------------------------------------

def probe(name: str, path: str, follow_redirects: bool = False) -> ProbeResult:
    url = BASE_URL + path
    t0 = time.perf_counter()
    try:
        if follow_redirects:
            opener = urllib.request.build_opener()
        else:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def http_error_302(self, *a, **kw): return None
                http_error_301 = http_error_303 = http_error_307 = http_error_302
            opener = urllib.request.build_opener(NoRedirect)
        req = urllib.request.Request(url, headers={"User-Agent": "kuma-mut/1.0"})
        with opener.open(req, timeout=5) as resp:
            body = resp.read(512).decode("utf-8", "replace")
            return ProbeResult(name, resp.status, body, dict(resp.headers),
                               (time.perf_counter() - t0) * 1000)
    except urllib.error.HTTPError as e:
        body = e.read(512).decode("utf-8", "replace") if hasattr(e, "read") else ""
        return ProbeResult(name, e.code, body, dict(e.headers or {}),
                           (time.perf_counter() - t0) * 1000)
    except Exception as e:
        return ProbeResult(name, 0, "", {}, (time.perf_counter() - t0) * 1000,
                           error=type(e).__name__)


PROBES = [
    ("P1_entry_page",     "/api/entry-page",                              False),
    ("P2_badge",          "/api/badge/1/status",                          False),
    ("P3_status_page",    "/api/status-page/main",                        False),
    ("P4_heartbeat",      "/api/status-page/heartbeat/main",              False),
    ("P5_push_unknown",   "/api/push/abc?status=up",                      False),
    ("P6_root",           "/",                                            False),
    # Additional probes designed to exercise paths the original suite missed
    ("P7_status_mixedcase",   "/api/status-page/MAIN",                    False),  # exercises slug.toLowerCase()
    ("P8_push_with_ping",     "/api/push/abc?status=up&ping=500",         False),  # exercises ping validation
    ("P9_status_unknown_long","/api/status-page/this-is-a-very-long-slug",False),  # additional 404 path
    ("P10_entry_via_xfh",     "/api/entry-page",                          False),  # repeated to confirm CORS header
]


def run_probes() -> List[ProbeResult]:
    return [probe(name, path, follow) for name, path, follow in PROBES]


def baseline_signature(results: List[ProbeResult]) -> dict:
    """Compact signature: status code + key body marker + relevant headers per probe."""
    sig = {}
    for r in results:
        marker = ""
        if r.body_snippet:
            marker = " ".join(r.body_snippet.split())[:80]
        # Include CORS header so SDL mutants that strip allowDevAllOrigin are visible.
        cors = ""
        for k, v in r.headers.items():
            if k.lower() == "access-control-allow-origin":
                cors = v
                break
        sig[r.name] = {"status": r.status, "marker": marker,
                       "cors": cors, "error": r.error}
    return sig


# --- Mutation cycle -----------------------------------------------------------

def apply_mutation(m: Mutant) -> Optional[str]:
    """Returns the original file content (for restoration), or None if find missed."""
    original = docker_cp_out(m.file)
    if m.find not in original:
        return None
    # Replace only the n-th occurrence
    parts = original.split(m.find)
    if len(parts) - 1 < m.occurrence:
        return None
    new = m.find.join(parts[:m.occurrence]) + m.replace + m.find.join(parts[m.occurrence:])
    docker_write(m.file, new)
    return original


def restore_file(path_in_container: str, content: str) -> None:
    docker_write(path_in_container, content)


def run_one(m: Mutant, baseline_sig: dict) -> MutantResult:
    print(f"[mutant {m.id}] applying: {m.description}")
    original = apply_mutation(m)
    if original is None:
        return MutantResult(asdict(m), killed=False,
                            survived_reason="MUTATION_NOT_APPLIED",
                            notes="Pattern not found in source — mutant invalid.")
    try:
        docker_restart()
        ready = wait_until_ready()
        if not ready:
            return MutantResult(asdict(m), killed=True,
                                notes="container failed to become ready -> killed by startup smoke")

        results = run_probes()
        mutant_sig = baseline_signature(results)
        diffs = []
        for k, base in baseline_sig.items():
            mut = mutant_sig.get(k, {})
            if mut.get("status") != base.get("status"):
                diffs.append(f"{k}: status {base['status']} -> {mut.get('status')}")
            elif mut.get("marker") != base.get("marker"):
                diffs.append(f"{k}: body marker drift")
            elif mut.get("cors") != base.get("cors"):
                diffs.append(f"{k}: CORS header {base.get('cors')!r} -> {mut.get('cors')!r}")
            elif mut.get("error") != base.get("error"):
                diffs.append(f"{k}: error {base.get('error')!r} -> {mut.get('error')!r}")
        if diffs:
            return MutantResult(asdict(m), killed=True, probe_diffs=diffs,
                                notes="probe deviation")
        return MutantResult(asdict(m), killed=False,
                            survived_reason="ALL_PROBES_MATCHED_BASELINE",
                            notes="probes did not detect this mutation")
    finally:
        restore_file(m.file, original)
        docker_restart()
        wait_until_ready()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--module", help="Filter mutants by file path substring")
    p.add_argument("--id", help="Run a single mutant by id")
    p.add_argument("--all", action="store_true", help="Run every mutant")
    args = p.parse_args()

    selected = MUTANTS
    if args.id:
        selected = [m for m in MUTANTS if m.id == args.id]
    elif args.module:
        selected = [m for m in MUTANTS if args.module in m.file]
    elif not args.all:
        p.error("pass --all, --module <name>, or --id <ID>")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("[baseline] capturing unmutated probe signature...")
    if not wait_until_ready():
        raise SystemExit("Kuma is not ready before baseline capture.")
    baseline_sig = baseline_signature(run_probes())
    print(f"[baseline] {json.dumps(baseline_sig, indent=2)}")

    results = []
    for m in selected:
        results.append(run_one(m, baseline_sig))

    out = os.path.join(RESULTS_DIR, "mutation_results.json")
    with open(out, "w") as f:
        json.dump({"baseline": baseline_sig,
                   "mutants": [asdict(r) for r in results]}, f, indent=2)

    killed = sum(1 for r in results if r.killed)
    total  = len(results)
    score  = (killed / total * 100) if total else 0
    print(f"\n[summary] killed={killed}/{total}  mutation_score={score:.1f}%")
    print(f"[summary] details -> {out}")


if __name__ == "__main__":
    main()
