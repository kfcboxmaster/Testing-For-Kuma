# Mutation Testing — Final Summary

## Combined results (automated + manual)

| Module | Operator(s) | Mutants | Killed | Survived | Mutation Score |
|---|---|---:|---:|---:|---:|
| `server/routers/status-page-router.js` | LOR, SDL, CRC, RVR, FCR | 5 | 2 | 3 | **40.0%** |
| `server/routers/api-router.js`         | RVR×2, LOR, CRC, SDL, ROR | 6 | 3 | 3 | **50.0%** |
| `server/password-hash.js` (manual)     | RVR×2, LOR, CRC, FCR | 5 | 2 | 3 | **40.0%** |
| `server/rate-limiter.js` (manual)      | CRC×2, ROR, RVR, FCR | 5 | 2 | 3 | **40.0%** |
| **Overall** | — | **21** | **9** | **12** | **42.9%** |

## Surviving mutants — root-cause categories

| # | Category | Count | Example | Recommended fix |
|---|---|---:|---|---|
| 1 | **Equivalent mutant** | 1 | API-SDL-1 (drop `allowDevAllOrigin` — no-op in production) | exclude / mark as equivalent |
| 2 | **Unreachable code path** in current test data | 4 | SPR-RVR-1 (response.json on found page — no page exists) | seed a status page fixture; create monitor fixture |
| 3 | **Behavior invisible to single probe** | 2 | SPR-CRC-1 (cache duration), RL-CRC-2 (raised ceiling) | add caching-behavior test; add brute-force test |
| 4 | **Code path not exercised by any test** | 5 | API-LOR-1 (trustProxy header), PH-LOR-1 (legacy SHA-1) | add proxy-header test; add legacy-hash fixture |

## Improvements ranked by ROI

1. **Add an admin-setup fixture** that programmatically completes Kuma's setup
   wizard (one-time socket emit). Unblocks at least 5 previously survived
   mutants (status-page reachable path + auth-bound mutants).
2. **Add a brute-force login test** in `tests/socket_api/test_auth.py` that
   exceeds `loginRateLimiter.tokensPerInterval` (20) and asserts the rate-limit
   payload. Kills RL-CRC-2, RL-RVR-1, RL-FCR-1.
3. **Add a CORS assertion** to a REST test for `/api/entry-page` when
   `NODE_ENV=development`. Kills API-SDL-1 in dev environments.
4. **Add a push-with-ping integration test** that asserts ping clamping
   (e.g., `?ping=99999999999` should succeed; `?ping=-1` should error). Kills
   API-ROR-1 outright.
5. **Add a proxy-header test** sending `X-Forwarded-Host` with `trustProxy=1`
   set in settings. Kills API-LOR-1.

## Reproduction

```bash
# Run all automated mutants (≈ 4 min, includes 11× container restart)
python3 tests/experimental/mutation/mutation_runner.py --all

# Single mutant by id
python3 tests/experimental/mutation/mutation_runner.py --id SPR-LOR-1

# By module
python3 tests/experimental/mutation/mutation_runner.py --module status-page-router
```

Raw probe traces: `tests/experimental/results/mutation_results.json`.
