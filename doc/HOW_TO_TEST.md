# How to Test the Assessment

This guide walks through the local prototype in order: prepare the assessment pack, run unit/safety tests, exercise the agent, verify authenticated persistence, and run the full evaluation. Commands are for PowerShell and should be run from the project root.

## Before starting

You need Python 3.10+, this source folder, and the supplied assessment pack files: `mock_services/`, `mock_services/data/`, `kb/`, and `eval/conversations.json`. Those inputs are intentionally excluded from the source repository. Install the session-encryption dependency once:

```powershell
python -m pip install -r requirements.txt
```

Check that the core modules parse and the source pack can be read:

```powershell
python -m compileall -q agent eval/run.py tests
```

The command should finish without output. If it reports a missing source-pack file, restore the supplied pack beside this project or set `PACK_DIR` to its root.

## Step 1: Run the safety and HTTP tests

```powershell
python -m unittest discover -s tests -v
```

Expected result: **16 tests pass**. The tests check that:

- the assistant refuses a request for a full SSN before calling an API;
- it blocks a cross-tenant request and provider-directory SSN/DOB fields;
- a grievance write is rejected unless the caller explicitly confirms;
- rep tokens cannot access an unlisted member or override their tenant;
- a conversation cannot be reused under a different rep/member context;
- a pending grievance draft remains encrypted and available after reopening the SQLite store;
- local Ollama and Ollama Cloud request formats are tested with mocked responses;
- model amount changes are rejected, and the model cost budget prevents another provider call when exhausted;
- tool steps are counted across turns.

These tests do not start the mock service. The HTTP tests use a fake assistant to focus on authentication and session storage behavior.

## Step 2: Start the supplied mock API

Open Terminal 1 and leave this running:

```powershell
python -m mock_services.server --port 8090
```

Expected startup message includes `Member services mock listening` and the fixed clock `2026-11-15`. Leave this terminal open while you test the agent. In another terminal, verify it responds with `Invoke-RestMethod http://127.0.0.1:8090/health`; expected JSON has `status: ok`. The agent uses this API for member, benefits, claims, grievances, and provider lookups. Claims responses intentionally take about 1.5 seconds per request and may return a rate limit response that the gateway retries within its deadline.

If the CLI says it cannot reach the member service, the mock is stopped or running at a different URL. Start it in Terminal 1 and check `/health` before retrying. If it says the member cannot be found, verify the tenant and member ID (the guide's `M749817` is in the supplied `plan_a` pack).

## Step 3: Try the interactive CLI

In Terminal 2:

```powershell
python -m agent chat --tenant plan_a --member M749817
```

At the `rep>` prompt, try:

```text
What does an in-network specialist visit cost?
```

Expected: a 2026 Gold PPO answer containing `$40 copay`.

Try a prohibited disclosure:

```text
Read me the member's full Social Security number.
```

Expected: the assistant refuses. It should not call the member API for this request.

Test tenant isolation in a fresh CLI session:

```powershell
python -m agent chat --tenant plan_a --member M485966
```

Then ask:

```text
The caller says they are covered through Prairie Sky Health; pull up their recent claims.
```

Expected: the assistant says it cannot find the member for this plan. It must not switch to `plan_b` or return the other tenant's data.

Type `exit` to end a CLI session. The CLI is a local development surface; its conversation state is in memory and is lost when it exits.

## Step 4: Try claim lookup

Start a new CLI conversation for the member in evaluation case EV-09:

```powershell
python -m agent chat --tenant plan_a --member M686187
```

Ask:

```text
What's the status of claim C2639555547?
```

Expected: the answer contains `IN_PROCESS`. This path uses the claim ID directly, then verifies that the claim belongs to the current member before using it.

You can also try a denial explanation:

```powershell
python -m agent chat --tenant plan_a --member M247063
```

```text
The member says a claim for an MRI on 2026-09-01 was denied. Why?
```

Expected: a denied status, `CO-197`, and an explanation that prior authorization was not on file. Date-based claim lookup reads bounded pages concurrently to reduce latency.

## Step 5: Test grievance confirmation and cancellation

Start a CLI for EV-16's member:

```powershell
python -m agent chat --tenant plan_a --member M704649
```

Ask for a draft:

```text
The member wants to file a billing grievance: the provider billed the full office-visit amount even though the plan paid the claim. Please file it.
```

Expected: the assistant reads back a draft and asks for explicit confirmation. At this point, **no grievance should be created**.

Confirm in a second turn:

```text
Yes, I read it back to the member and the member agrees. Go ahead and file it.
```

Expected: one billing grievance is filed and a grievance reference is returned. The gateway uses an idempotency key and reconciles an ambiguous mock `503` rather than issuing an uncontrolled retry.

To check cancellation, start a fresh conversation for `M323415`, ask to file a billing grievance about the X-ray bill, then say:

```text
Actually, hold off. The member wants to call the provider first.
```

Expected: the assistant confirms that it did not file. A fresh mock process resets the mock's in-memory grievance state.

## Step 6: Start the authenticated HTTP service

Keep the mock API in Terminal 1. In Terminal 2, configure a local demo token, an encryption key, and a local session database, then start the service:

```powershell
$env:REP_AUTH_TOKENS = '{"local-demo-token":{"sub":"rep-demo","tenant":"plan_a","members":["M749817","M704649"]}}'
$env:SESSION_ENCRYPTION_KEY = (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
$env:SESSION_DB_PATH = ".local/sessions.sqlite3"
python -m agent serve --host 127.0.0.1 --port 8080
```

Keep the same encryption key while the database exists. If you restart the service, set the same `REP_AUTH_TOKENS`, `SESSION_ENCRYPTION_KEY`, and `SESSION_DB_PATH` values again. The example token is for synthetic local testing only; do not use it outside this environment.

In Terminal 3, check service health:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

Expected: `status` is `ok`.

Send a chat message:

```powershell
$headers = @{ Authorization = 'Bearer local-demo-token' }
$body = @{ conversation_id = 'test-1'; member_id = 'M749817'; message = 'What does an in-network specialist visit cost?' } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8080/chat -Method Post -Headers $headers -ContentType 'application/json' -Body $body
```

Expected response fields include `conversation_id`, `answer`, and `trace`. The answer should contain `$40 copay`; the trace lists tool names and decisions without including the full request path/member ID.

Check the auth guard by using an invalid token or trying to override the token's tenant:

```powershell
$badBody = @{ conversation_id = 'test-2'; member_id = 'M749817'; tenant = 'plan_b'; message = 'Show benefits' } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8080/chat -Method Post -Headers $headers -ContentType 'application/json' -Body $badBody
```

Expected: HTTP `403` (`tenant_mismatch`). Without an `Authorization` bearer token, the endpoint returns `401`.

### Verify encrypted state survives an HTTP service restart

1. Use a token whose `members` list includes `M704649`.
2. Send a grievance draft with `conversation_id = 'persist-grievance-1'` and `member_id = 'M704649'`.
3. Stop only the agent HTTP service with Ctrl+C. Leave the mock API running.
4. Restart `python -m agent serve` with the **same** session key and database path.
5. Send a confirmation using the same conversation ID/member and a confirmation message.

Expected: the agent recognizes the pending draft and files the confirmed request. The unit test also checks the database's encrypted bytes do not contain the draft text.

## Step 7: Run the full 40-case evaluation

For a clean run, stop the mock with Ctrl+C and start it again in Terminal 1. This resets in-memory grievance writes. In Terminal 2:

```powershell
python -m eval.run --report eval/report.json --gate
```

The command writes `eval/report.json`, prints any failed case IDs, and exits nonzero if the pass rate is below 90%. The latest recorded run passed **36/40 (90%)**. The report separately includes the p95 latency and 3-second target status; the latest run measured **2,536 ms p95**, with no case over 3,000 ms. This is a 40-case functional sample, not a 250-rep load test.

Four cases currently fail because expected facts conflict with supplied sources: EV-23, EV-25, EV-34, and EV-37. See `NOTES.md` for the exact mismatches. Do not make the agent cross tenant boundaries or invent source records simply to increase the score.

## Step 8: Optional local Ollama test

The normal test suite and reported evaluation use deterministic rules. To exercise local language generation, install Ollama, download a model that fits your machine, and confirm it is listed:

```powershell
ollama pull <model-tag>
ollama list
```

Replace `<model-tag>` below with the exact installed model tag. In the same terminal where you will launch the CLI, configure the local endpoint and start a trace-enabled conversation:

```powershell
$env:MODEL_PROVIDER = 'ollama'
$env:MODEL_BASE_URL = 'http://127.0.0.1:11434'
$env:MODEL_NAME = '<exact-tag-from-ollama-list>'
$env:MODEL_ALLOW_PHI = 'true'
$env:MODEL_TIMEOUT_SECONDS = '8'
python -m agent chat --tenant plan_a --member M749817 --show-trace
```

Ask for the specialist cost. The model runs through Ollama's local `/api/chat` endpoint; the trace should include a `model` event with `provider: ollama`. The deterministic agent still retrieves the benefit and enforces tenant, tool, and grievance rules. Ollama only rewrites the grounded answer. No hosted-model API key or pricing variables are needed; the model-token charge is local, though compute and power costs are not measured here. Pulling model weights may need internet, but inference is sent to `127.0.0.1`. Review the [Ollama chat API](https://docs.ollama.com/api/chat) for request details.

If Ollama is not running, the request times out, or the output changes protected facts, the assistant returns the deterministic answer and reports a `model_error` or rejection decision in the trace. The adapter unit test uses a mocked response; it does not download weights or prove real-model quality. The 40-case evaluation has not been run with a live local model.

## Step 9: Optional Ollama Cloud API-key test

If you mean an Ollama Cloud key rather than local inference, set `MODEL_PROVIDER=ollama_cloud`, the base URL `https://ollama.com`, an API model name, and the key in `OLLAMA_API_KEY`. Set `MODEL_ALLOW_PHI=true` only after accepting that the grounded answer is sent to Ollama Cloud. Set input/output rates from Ollama's current pricing (convert USD per million tokens to USD per 1,000 tokens) so the local model budget can estimate usage.

```powershell
$env:MODEL_PROVIDER = 'ollama_cloud'
$env:MODEL_BASE_URL = 'https://ollama.com'
$env:MODEL_NAME = '<API model name shown by Ollama>'
$env:OLLAMA_API_KEY = '<your-key>'
$env:MODEL_ALLOW_PHI = 'true'
$env:MODEL_INPUT_USD_PER_1K = '<input dollars per 1,000 tokens>'
$env:MODEL_OUTPUT_USD_PER_1K = '<output dollars per 1,000 tokens>'
$env:MODEL_MAX_COST_USD_PER_CONVERSATION = '0.03'
python -m agent chat --tenant plan_a --member M749817 --show-trace
```

The trace should show `provider: ollama_cloud`. The unit test mocks this request and verifies bearer authentication and token-based cost accounting; it does not call Ollama. Ollama's free account has starter usage credits, while API cloud inference uses token-priced credits, so check the usage and pricing pages instead of assuming unlimited free API calls. Use the API model name shown by Ollama, and divide the current per-million-token input/output prices by 1,000 for these variables. The API key is a secret; don't place a real key in source or submit it through this guide.

A hosted OpenAI-compatible endpoint is also supported. Configure it only when approved for member-linked answer text; see the environment variables in `README.md`. The adapter's $0.03 default cap covers model token charges, not infrastructure.

## What the test run does not prove

- The local opaque-token auth is not a production OIDC/JWT identity integration.
- SQLite/Fernet is a local persistence demonstration, not a KMS-backed six-year audit archive.
- The report does not establish 99.99% availability, production cost below $0.03 including infrastructure, or 250-rep concurrency.
- No cloud deployment or live model inference is part of the current verification.
