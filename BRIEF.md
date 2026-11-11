# Take-home task: Governed multi-tenant member-services agent

**Role:** AI Architect. **Effort:** 8 to 10 hours. **Window:** 7 calendar days from when you receive this.

## Context

A healthcare services company runs an AI assistant for the member-services representatives ("reps") of two client
health plans. The clients are tenants of the same platform: `plan_a` and `plan_b`. During a call, a rep asks the
assistant about the member's benefits and claims, and can ask it to file a grievance on the member's behalf. A
grievance is filed only after the rep confirms. The two clients' data must never mix.

You will design this platform and build a working slice of it. Emids uses this task to see how you make
architecture decisions and whether you can still build what you design.

## What to build

All three parts are required. The code is the main part.

**1. A working vertical slice**

- An agent that answers rep questions for one tenant and one member at a time, using the supplied mock APIs and plan
  documents.
- A **tool gateway** that every tool call goes through. The gateway enforces:
  - tenant isolation;
  - PHI minimisation, both in what reaches the model and in what reaches the logs;
  - human confirmation before any write;
  - per-conversation budgets for steps, cost and latency.
- Retrieval over the tenants' plan documents in `kb/`.
- A grievance-filing tool that is safe under retries.
- A trace of every step of a conversation (model calls, tool calls, gateway decisions).
- An HTTP API or a CLI. A rep conversation must be able to span several turns (for example, the confirmation step).
- The agent may use the third-party provider directory described in `tools/`.

**2. An evaluation harness**

- Runs the cases in `eval/conversations.json` against your agent and scores them.
- Includes a regression gate that could run in CI: it fails the build when quality drops below thresholds you set
  and justify.
- Produces a report that you commit to the repository.

**3. A design document**

At most 4 pages, plus one architecture diagram. It covers:

- the target production deployment on one cloud of your choice (AWS, Azure or GCP);
- a one-page mapping of that deployment to a second cloud (one of the other two);
- a threat model;
- 3 to 5 Architecture Decision Records (context, decision, alternatives, consequences).

Your design should respond to the non-functional requirements in `data/README.md`.

It will be used by staff on real data; build it the way you would for production.

Show us how you know it works.

## What we provide

| Path | Contents |
|---|---|
| `data/README.md` | Tenants and tokens, the as-of date, the API reference, and the client's non-functional requirements. Read it first. |
| `mock_services/server.py` | Mock member, claims, benefits and grievance APIs for both tenants, plus the directory. Standard library Python: `python mock_services/server.py --port 8090`. |
| `mock_services/data/` | Backing data for the mock. |
| `kb/plan_a/`, `kb/plan_b/` | Plan documents in Markdown with front-matter: benefit summaries, member services guide, claim codes. |
| `tools/third_party_provider_directory.json` | MCP-style tool manifest from an external provider-directory vendor. |
| `eval/conversations.json` | 40 rep conversations with the tenant, the member and the expected outcome. |

## Deliverables

One public GitHub repository containing:

- the code for the slice, with tests;
- a `README.md` with setup and run steps (start the mock, run the agent, run the evaluation), and the model you
  developed with;
- the evaluation harness, its regression gate, and the committed report from your last run;
- the design document and diagram (Markdown, or PDF with its source);
- `NOTES.md` (see Submission).

We will run your solution against our own copy of the pack, so make the pack location and the model provider
configurable.

## Ground rules

- **AI tools are welcome.** Use ChatGPT, Claude, Copilot, Cursor or anything else, with your best judgment. You own every line you submit: in a follow-up session we will ask you to walk through your code and change it live.
- **Any LLM is fine.** Use an open-weights model (for example through Ollama) or a paid API. We will run your solution, and we may use a different model or provider from the one you used. Make that easy, and tell us in the README which model you developed with.
- **Public GitHub repository, real history.** Create the repository when you start and commit as you work. We read the commit history to understand how your solution evolved. A single upload of finished code, or rewritten/squashed history, counts against you.
- **Do not commit the supplied data or mock services** to your public repository. Keep them out with `.gitignore`, and make the data location configurable. We have our own copy.
- **Treat the supplied files as you would real-world data.** The data is synthetic, but handle it as if it were real patient or member data.
- **Examples in this brief show format only.** They are not test answers.
- **Stay within the timebox.** It is a guide to scope, not a race. If you run out of time, tell us what you would do next instead of rushing it in.

## Submission

Reply to the email you received with:
1. The link to your public GitHub repository and the hash of your final commit (made before the deadline).
2. Nothing else is required. Everything we need should be in the repository, including a short `NOTES.md` (one page at most): the decisions and assumptions you made, anything in the data that surprised you, what you would do with another day, and how you used AI tools (where they helped, and where they were wrong).
