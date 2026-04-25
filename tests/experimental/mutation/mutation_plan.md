# Mutation Test Plan — Uptime Kuma

## Goal
Quantify the effectiveness of the existing automated test suite (`tests/rest_api/`,
`tests/socket_api/`) by injecting controlled faults into Kuma's server-side
JavaScript modules and measuring detection rate.

## Why a custom harness instead of Stryker
Stryker (the standard JS mutator) requires a running Node toolchain and the
project's own test runner. The graded WSL environment has no Node CLI, and
Kuma's bundled tests need a build pipeline we cannot reproduce here. Instead we
patch each mutant **into the running Docker container**, restart Kuma
(2 s cold start measured), and run a **probe suite** of HTTP requests +
selected pytest cases. A mutant is *killed* when any probe fails; otherwise
it *survives*.

The harness lives at `tests/experimental/mutation/mutation_runner.py` and is
fully reproducible (`python3 mutation_runner.py --module status-page-router`).

## Modules under test (selected from midterm risk analysis)

| # | Module | Reason for selection | Observable surface |
|---|---|---|---|
| 1 | `server/routers/status-page-router.js` | Status pages are public-facing; broken routing here is a top-severity availability bug | `GET /api/status-page/:slug`, `GET /api/status-page/heartbeat/:slug` |
| 2 | `server/routers/api-router.js` | Houses the badge, entry-page, and push endpoints — all hot-paths | `GET /api/entry-page`, `GET /api/badge/:id/status`, `GET /api/push/:token` |
| 3 | `server/password-hash.js` | Critical security primitive: silent regressions enable auth bypass | login flow (analyzed manually — see §Manual mutants) |
| 4 | `server/rate-limiter.js` | Login rate-limiter; mutation could disable brute-force protection | login rate-limit behavior (analyzed manually) |

## Mutation operators
| Operator | Description | Example |
|---|---|---|
| LOR | Logical operator replacement | `if (!statusPage)` → `if (statusPage)` |
| ROR | Relational operator replacement | `< 0` → `<= 0`, `>` → `>=` |
| AOR | Arithmetic operator replacement | `+` → `-` |
| CRC | Constant replacement | `tokensPerInterval: 20` → `0` |
| SDL | Statement deletion | remove `slug.toLowerCase()` |
| RVR | Return-value replacement | `return false` → `return true` |
| FCR | Function-call removal | comment out `callback(...)` |

## Probe suite
Each mutant is judged by the same probe suite, executed after the container
has been restarted and the `/api/entry-page` endpoint responds:

| Probe | Expectation | Detects mutants in |
|---|---|---|
| P1 `GET /api/entry-page` | `200 + {"type":"entryPage", ...}` | api-router |
| P2 `GET /api/badge/1/status` | `200 + content-type: image/svg+xml` | api-router, util-server |
| P3 `GET /api/status-page/main` | `404 + status:"fail"` | status-page-router (slug not found) |
| P4 `GET /api/status-page/heartbeat/main` | `200 + heartbeatList: {}` | status-page-router |
| P5 `GET /api/push/abc?status=up` | `404` (token unknown) | api-router |
| P6 `GET /` | `302` redirect to `/dashboard` | server.js core |

If any probe deviates, the mutant is **killed**. If all probes match the
unmutated baseline, the mutant **survives**, indicating a test-suite gap.

## Manual mutants (modules with no anonymous surface)

`password-hash.js` and `rate-limiter.js` are exercised only behind the
authenticated socket API. The deployed test container does not have an admin
user (Kuma 2.x setup is interactive socket.io), so we cannot drive
authenticated tests in this environment. For these two modules we document
**static mutants** and trace which `tests/socket_api/test_auth.py` test cases
would catch each one — see `manual_mutants.md`.
