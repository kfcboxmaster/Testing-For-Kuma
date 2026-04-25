# Manual Mutation Analysis — `password-hash.js` & `rate-limiter.js`

These two modules sit behind the authenticated socket API. The Docker test
environment used in the automated harness does not have an admin user
configured (Kuma 2.x setup is interactive over Socket.IO and could not be
driven from the WSL toolchain), so we cannot exercise them through HTTP probes.
We therefore document the mutants statically and trace each to the existing
test that **would** kill it under a configured Kuma instance.

The relevant existing tests are in
`tests/socket_api/test_auth.py` (login / logout / wrong password).

## `server/password-hash.js`

| Mutant | Operator | Change | Killed by | Verdict |
|---|---|---|---|---|
| PH-RVR-1 | RVR | `exports.verify` always returns `true` | `test_login_invalid_password` (logs in with bad password — should fail; mutant lets it succeed) | KILLED |
| PH-RVR-2 | RVR | `exports.verify` always returns `false` | `test_login_valid_credentials` (correct creds rejected) | KILLED |
| PH-LOR-1 | LOR | `isSHA1` uses `endsWith` instead of `startsWith` | No legacy SHA-1 hash in fresh DB → mutant has no observable effect on existing tests | **SURVIVES** |
| PH-CRC-1 | CRC | `saltRounds = 10` → `1` | bcrypt still produces valid hashes, only weaker; existing tests do not assert hash strength | **SURVIVES** |
| PH-FCR-1 | FCR | drop the rehash `R.exec(...)` block | tests do not assert that legacy SHA-1 hashes get upgraded | **SURVIVES** |

**Coverage gap:** the suite needs (a) a fixture loading a SHA-1 legacy hash and
asserting upgrade-on-login, (b) a strength assertion against
`bcrypt.getRounds(hash)` after `generate`.

## `server/rate-limiter.js`

| Mutant | Operator | Change | Killed by | Verdict |
|---|---|---|---|---|
| RL-CRC-1 | CRC | `loginRateLimiter.tokensPerInterval: 20 → 0` | first authenticated test (`test_login_valid_credentials`) immediately rate-limited | KILLED |
| RL-CRC-2 | CRC | `loginRateLimiter.tokensPerInterval: 20 → 1000` | no test triggers the limit, so the lifted ceiling is invisible | **SURVIVES** |
| RL-ROR-1 | ROR | `if (remainingRequests < 0)` → `<= 0` | first call now blocked because `removeTokens` returns 0 on first call (`fireImmediately:true`) → `test_login_valid_credentials` fails | KILLED |
| RL-RVR-1 | RVR | `pass()` always returns `true` | needs a brute-force test that exceeds 20 attempts/min — none exists | **SURVIVES** |
| RL-FCR-1 | FCR | drop the `callback({ ok:false })` invocation | needs a test asserting the error message body sent to the client when rate-limited — none exists | **SURVIVES** |

**Coverage gap:** add a brute-force test (loop 25× with bad password, assert
the 21st attempt receives `{ok: false, msg: "Too frequently..."}`) — kills
RL-CRC-2, RL-RVR-1, and RL-FCR-1 in one stroke.

## Summary

| Module | Mutants | Killed | Survived | Score |
|---|---:|---:|---:|---:|
| password-hash.js | 5 | 2 | 3 | 40.0% |
| rate-limiter.js  | 5 | 2 | 3 | 40.0% |
