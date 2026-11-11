# Assessment Progress

## Workstreams

| Workstream | Status | Completed | Remaining |
|---|---|---|---|
| Governed working slice | Implemented locally | CLI and authenticated HTTP API; rep tokens scoped to tenant and member allowlists; encrypted SQLite conversation state; policy-enforced gateway; tenant-filtered plan lookup; bounded concurrent claims reads; PHI-minimized traces; explicit grievance confirmation and idempotency; per-conversation 24-step budget and 12-second question deadline. | Replace demo opaque tokens with OIDC/JWT and managed identity; use KMS and managed durable storage; add immutable six-year audit; perform production security review. |
| Evaluation harness | Implemented; quality and sample latency gates pass | Forty-case harness and report; 90% quality gate; p95 latency summary. Current result is 36/40 (90%), p95 2,536 ms, 0 cases above 3 seconds. Sixteen unit/integration tests pass. | Four supplied expected facts conflict with the tenant-scoped source data (listed below). Run representative concurrency/load tests and real model cost tests. |
| Production design | Complete as a design artifact | AWS one-region/multi-AZ design with diagram, Azure mapping, NFR response, threat model, five ADRs, plus interview guide. | Validate availability, cost, capacity and recovery against actual selected cloud services. Cloud deployment is not required for this assessment. |
| Submission repository | Not complete | Public-pack exclusions are in `.gitignore`; source, docs, tests, and report are present locally. | No commit history or public remote was created: the managed workspace permits read-only `.git` access, and no destination GitHub repository was provided/configured. |

## Known evaluation fixture conflicts

- **EV-23:** expects Prairie Sky virtual-care terms for a Harborview member; only the supplied Prairie Sky document contains those terms.
- **EV-25:** expects the 2027 Silver HMO deductible while the pack's as-of date is in 2026 and the 2026 plan document applies.
- **EV-34:** expects `PAID`; the mock API record for the member and claim is `DENIED`.
- **EV-37:** expects the Value HDHP generic-drug cost while the member API says Choice PPO and its document gives a different cost.

The agent follows authenticated tenant and source records. It does not alter or bypass these boundaries to match contradictory facts.

## Current verification

- `python -m unittest discover -s tests -v`: 16 tests passed, including auth, member scoping, encrypted persistence across store recreation, model fact guard, and budget checks.
- `python -m eval.run --report eval/report.json --gate`: **36/40 passed; quality gate PASS at 90%.**
- Evaluation sample p95: **2,536 ms** against the 3,000 ms target; zero sample cases exceeded 3,000 ms. This is a 40-case mock-pack result, not a 250-rep load test.
- Model provider modes support local Ollama, Ollama Cloud API keys, and hosted OpenAI-compatible endpoints, but evaluation remained `rules`. No local model was installed or run, and no hosted endpoint was called. The adapter paths were tested with mocked responses; live provider credentials were not used. Production cost and six-year audit retention are unverified.
