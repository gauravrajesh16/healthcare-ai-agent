# Interview Guide: Member Services Assistant

This guide gives you a simple way to explain the project. You can read the short talk track first, then use the examples and notes for follow-up questions.

## A 30-second explanation

> ?I built a prototype assistant for member-service reps at two health plans. It answers benefit and claim questions using the plan's data and documents. A policy gateway checks every data request so one plan's information cannot be used for the other plan. The assistant can draft a grievance, but a rep must confirm before it is filed. The default version uses deterministic rules. An optional local or hosted LLM can reword a grounded answer, but it never gets to choose tools or approve a write.?

## What the assistant does

A representative works with one member at a time. They can ask:

- **Benefits:** ?What does a specialist visit cost?? The assistant reads the member's plan and the matching plan-year document.
- **Claims:** ?What happened to this claim?? The assistant checks the member's claims and explains the status or denial reason.
- **Grievances:** ?Please file a complaint.? The assistant drafts a summary, reads it back, and waits. It files only after the rep confirms.
- **Provider search:** It searches by specialty, ZIP code, and the member's network. It does not send SSN or date of birth to the vendor.

The two plans are `plan_a` (Harborview) and `plan_b` (Prairie Sky). A member record, document, response, or cache entry from one plan must not appear in the other plan's conversation.

## Walk through one request

For a benefit question:

1. The rep's tenant and member are fixed for the conversation.
2. The assistant asks the gateway for the member's enrollment and benefit accumulators.
3. It selects a document for that tenant, product, and plan year.
4. It answers from those sources and records a trace of the tool decisions.

The model does not make the API calls or decide whose data is allowed. The gateway enforces that policy in code.

For a grievance, the assistant creates a draft first. The confirmation applies to that exact draft and conversation. The gateway uses an idempotency key so a retry will not create a second grievance. If the mock API gives an unclear timeout response, the agent checks for the grievance instead of blindly submitting again.

## How to explain the AI and Ollama choices

The default provider is `rules`: it makes no model call. The prototype also supports:

- **Local Ollama (`ollama`):** the grounded answer is sent to Ollama running on the same machine. No API key is needed.
- **Ollama Cloud (`ollama_cloud`):** uses an Ollama API key and hosted inference. It is a cloud service, not local inference; configure the model's token rates because usage credits are consumed.
- **OpenAI-compatible hosted endpoint:** optional, also requires explicit PHI approval and token rates.

For all three, this prototype's LLM role is limited to rewording an answer after the deterministic agent retrieves its facts. It does not plan or call tools. The `MODEL_ALLOW_PHI=true` setting is required because an answer can include member-linked information. The evaluation run used `rules`; no live LLM request was made. The optional Ollama Cloud API follows Ollama's [Cloud API](https://docs.ollama.com/cloud); its free plan includes starter credits, not unlimited inference.

## How the safety pieces fit together

| Term | Plain explanation | Example in the prototype |
|---|---|---|
| Tenant isolation | Keep each health plan's data separate everywhere. | Tenant comes from the rep token in HTTP; every API path and document lookup uses that tenant. |
| Tool gateway | A checkpoint every data or write request must pass. | It checks tenant, fields, call count, time, and confirmation. |
| Minimum PHI | Send and store only the information needed for the task. | Full SSNs are refused; directory searches use only specialty, ZIP, and network; traces omit member IDs from paths. |
| Human confirmation | The rep must approve a grievance draft before filing. | A second-turn confirmation is bound to the saved draft. |
| Idempotency | Repeating the same write request does not create a duplicate. | The gateway supplies the same key when reconciling an uncertain grievance response. |
| Encrypted state | Pending drafts should remain private when saved. | The HTTP demo encrypts session payloads in SQLite and binds sessions to a rep, tenant, and member. |

## Production design in one minute

> ?For production I chose AWS in one region, with the service and managed data spread across availability zones. Rep identity determines tenant access. A stateless API service calls the policy gateway; plan documents use required tenant, product, and date filters. Session state is stored durably, writes use confirmation plus idempotency, and audit records go to encrypted immutable storage for six years. Azure equivalents are mapped in the design, but portability still needs service-by-service testing.?

The design diagram is in `doc/ARCHITECTURE.md`. It is a target architecture, not a cloud deployment. Multi-AZ improves availability, but a one-region design still has regional-outage risk.

## NFRs and what was measured

- **Latency:** The 40-case mock evaluation measured p95 of 2,536 ms, with no case over 3 seconds. Claim pages are read concurrently to reduce delay. This is a functional sample, not a load test.
- **Scale:** The proposed service can scale horizontally, but the 250-concurrent-rep target has not been load-tested.
- **Cost:** Hosted model token usage has a configurable per-conversation estimate cap. Overall cloud/infrastructure cost has not been measured. Local Ollama also uses machine compute and power.
- **Availability:** The design uses multiple availability zones in one region. The 99.99% target is not proven by a deployed service or recovery test.
- **Audit:** The design calls for six-year immutable retention. The local prototype does not implement that archive.

## Evaluation result and four data conflicts

The harness currently passes **36 of 40 cases (90%)**, which meets its quality gate. Four expected answers conflict with the supplied source records:

- **EV-23:** expects Prairie Sky virtual-care terms for a Harborview member.
- **EV-25:** expects the 2027 deductible although the pack's current date is in 2026.
- **EV-34:** expects `PAID`, while the mock claim is `DENIED`.
- **EV-37:** expects Value HDHP drug coverage, while the member's enrollment says Choice PPO.

I kept the assistant aligned with tenant and source records instead of returning unsupported answers. The exact evidence is in `NOTES.md` and `eval/report.json`.

## Useful repository paths

- `agent/app.py`: conversation behavior and source selection.
- `agent/gateway.py`: tenant checks, tool budgets, data minimization, and writes.
- `agent/model.py`: deterministic default plus optional Ollama/hosted answer rewriter.
- `agent/session_store.py`: encrypted durable HTTP conversation state.
- `agent/__main__.py`: CLI and authenticated HTTP service.
- `tests/`: safety, authentication, session, budget, and model adapter tests.
- `eval/run.py` and `eval/report.json`: case scoring and the latest report.
- `doc/ARCHITECTURE.md`: production diagram, NFRs, threat model, cloud mapping, and decisions.
- `doc/HOW_TO_TEST.md`: step-by-step test instructions.

## Questions you may be asked

**Why not let the LLM call the APIs itself?**

Because the LLM should not decide which tenant it can access, which member fields may be sent, or whether a write is authorized. The gateway makes those decisions and logs them.

**Why require a second turn for a grievance?**

The rep must read the summary back and get the member's agreement. The confirmation is for a specific saved draft, and idempotency protects against duplicates when a response is lost.

**Is this production-ready?**

No. It demonstrates the core workflow and safety controls. Production still needs an enterprise identity provider, managed keys and storage, a six-year audit archive, security review, cloud deployment, and load/cost/availability tests.

**What would you do next?**

Resolve the four evaluation-fixture conflicts with the assessment owner, test an approved model against the full suite, load-test 250 concurrent reps, verify total cost and recovery targets, and publish the source with a real commit history.
