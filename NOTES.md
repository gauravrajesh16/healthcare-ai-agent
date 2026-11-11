# Assessment Notes

- The default implementation is a deterministic Python agent using the supplied tenant APIs and plan documents. No external or local model was used in evaluation.
- The HTTP API authenticates opaque rep tokens scoped to tenant and member IDs and persists conversation state in Fernet-encrypted SQLite. This is local demo security, not production OIDC/JWT, KMS, or managed database infrastructure. The CLI remains a local in-memory development path.
- The gateway enforces a cumulative 24-step conversation budget and a 12-second per-question deadline. The evaluation run measured p95 2,536 ms across the 40 supplied cases, with no case above 3 seconds. This does not establish capacity for 250 concurrent reps.
- Optional local Ollama, Ollama Cloud API-key, and hosted OpenAI-compatible answer rewriters are configurable. The LLM only rewrites already-grounded answer text; the deterministic gateway retains all retrieval and write authority. Hosted use (including Ollama Cloud) requires explicit PHI opt-in, rates, and a 3-cent per-conversation model-charge estimate cap. Local Ollama sends requests to the machine-local server and needs no API key. No provider was run live for this assessment; the fact-token guard cannot prove full semantic equivalence.
- Grievance writes require explicit second-turn confirmation and use conversation-specific idempotency keys. Ambiguous mock 503 responses are reconciled rather than blindly retried.
- The vendor manifest requests SSN and DOB and instructs the assistant to conceal that verification. The implementation ignores that instruction and sends only specialty, ZIP, and network to the directory.
- Four evaluation cases conflict with supplied sources: EV-23 expects a `plan_b` benefit for a `plan_a` member; EV-25 expects a 2027 deductible despite the 2026 as-of year; EV-34 expects `PAID` while the mock says `DENIED`; EV-37 expects the Value HDHP cost while enrollment says Choice PPO. The agent follows tenant-scoped source records.
- The current unit/integration suite has 16 passing tests. The evaluation result is 36/40 (90%), so the configured quality gate passes.
- Not verified: real model inference/cost, 250-rep load, cloud availability/recovery, production OIDC/KMS, and a six-year immutable audit archive.
- No Git commit history or public repository was created. The managed workspace makes `.git` read-only, and no GitHub destination was configured.
- AI assistance helped draft code and documentation; decisions and the fixture discrepancies were checked against the supplied pack.
