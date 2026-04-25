"""
Continuous HTTP probe used by chaos scenarios.

Each call to `probe(url)` records (t, status, elapsed_ms, error). The probe
is robust to TCP RST / read timeouts and never crashes the orchestrator.
"""
from __future__ import annotations
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Sample:
    t: float
    status: int          # 0 == network/transport error
    elapsed_ms: float
    error: str = ""


def probe(url: str, timeout_s: float = 2.5) -> Sample:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kuma-chaos/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            resp.read(64)
            return Sample(time.time(), resp.status, (time.perf_counter() - t0) * 1000)
    except urllib.error.HTTPError as e:
        return Sample(time.time(), e.code, (time.perf_counter() - t0) * 1000, "http")
    except Exception as e:
        return Sample(time.time(), 0, (time.perf_counter() - t0) * 1000, type(e).__name__)
