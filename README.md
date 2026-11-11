# Member Services Agent (Assessment Slice)

A standard-library Python prototype for a rep assistant serving one tenant and member per conversation. It uses the supplied mock APIs and tenant/product/year-filtered Markdown plan documents. Every API tool call passes through `agent/gateway.py`.

## Setup

Use Python 3.10 or newer and the supplied pack (`mock_services/`, `mock_services/data/`, `kb/`, `eval/conversations.json`). Install the sole additional dependency for encrypted persistent sessions:

```powershell
python -m pip install -r requirements.txt
```

The provided mock, synthetic data, knowledge base, vendor manifest, and evaluation cases are excluded from this source repository; keep your assessment pack alongside it.

## Run the mock and CLI

Terminal 1:

```powershell
python -m mock_services.server --port 8090
```

Terminal 2:

```powershell
python -m agent chat --tenant plan_a --member M749817
```

The CLI is a local development surface. It uses the deterministic `rules` provider by default and keeps its conversational state in process memory.

## Authenticated HTTP service

Before starting the service, set a local token scoped to a tenant and member allowlist, a Fernet encryption key, and a local database path. Keep these values out of source control and use a strong random token outside a local demo.

```powershell
$env:REP_AUTH_TOKENS = '{"local-demo-token":{"sub":"rep-demo","tenant":"plan_a","members":["M749817","M704649"]}}'
$env:SESSION_ENCRYPTION_KEY = (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
$env:SESSION_DB_PATH = ".local/sessions.sqlite3"
python -m agent serve --host 127.0.0.1 --port 8080
```

The opaque bearer token determines the tenant and rep subject; the request cannot override the tenant. Each token also limits accessible member IDs (`"*"` is for synthetic local demos only). Session payloads, including pending grievance drafts, are Fernet-encrypted before SQLite persistence. Preserve the same encryption key across restarts or the existing sessions cannot be read.

Example call from another PowerShell terminal:

```powershell
$headers = @{ Authorization = 'Bearer local-demo-token' }
$body = @{ conversation_id = 'interview-demo-1'; member_id = 'M749817'; message = 'What does an in-network specialist visit cost?' } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8080/chat -Method Post -Headers $headers -ContentType 'application/json' -Body $body
```

Reuse the same conversation ID for follow-up turns. HTTP returns `401` without a valid token, `403` for a tenant/member scope mismatch, and `409` if a conversation ID is reused by a different rep/member context. The demo token file is represented by an environment variable, so it is not persisted or logged by the service.

For a production identity system, replace opaque-token lookup with OIDC/JWT validation and tenant claims from the identity provider. Use a managed KMS key and durable database rather than local Fernet/SQLite. The local HTTP service is not designed for internet exposure.

## Local Ollama model (optional)

The default `MODEL_PROVIDER=rules` makes no model call. For local inference, install Ollama, pull a model that fits your machine, and start its local service. Then configure the adapter:

```powershell
ollama pull <model-tag>
ollama list
$env:MODEL_PROVIDER = 'ollama'
$env:MODEL_BASE_URL = 'http://127.0.0.1:11434'
$env:MODEL_NAME = '<exact-tag-from-ollama-list>'
$env:MODEL_ALLOW_PHI = 'true'
$env:MODEL_MAX_OUTPUT_TOKENS = '300'
$env:MODEL_TIMEOUT_SECONDS = '8'
python -m agent chat --tenant plan_a --member M749817 --show-trace
```

`<model-tag>` is a placeholder; replace it with a model you have installed. In this mode there is no hosted-model API key or token-rate setting. The model runs on the local Ollama service and has no direct tool access. The agent first obtains tenant-filtered facts through its deterministic gateway, then sends only the grounded answer text to Ollama for wording. The trace should include a `model` event with `provider: ollama`. For this synthetic member data, explicitly setting `MODEL_ALLOW_PHI=true` acknowledges that member-linked answer text is sent to the local model process. Pulling model weights may require an internet connection; inference calls use the local endpoint. Ollama's [chat API](https://docs.ollama.com/api/chat) documents the native `/api/chat` request used here.

The model can be too slow for the 12-second per-question deadline on some hardware, especially when first loading. If it times out or fails the literal fact guard, the service falls back to the deterministic answer. The fact guard checks amounts, dates, statuses, and codes; it cannot prove all prose is semantically equivalent. The default evaluation report uses `rules`, not a live local model.


## Ollama Cloud with an API key (optional)

If you have an Ollama Cloud API key, use provider `ollama_cloud`. This sends the grounded answer to Ollama-hosted inference; it is **not local inference** and does not require the Ollama desktop app. Ollama documents the native `POST https://ollama.com/api/chat` endpoint and bearer API key. The free account includes starter usage credits, while cloud models consume usage credits at model token rates; a free API key should not be treated as unlimited free inference. Check the current [Ollama pricing and usage page](https://ollama.com/pricing) and set the rates for your selected model.

Set the API key only in the process environment (never paste it into code or commit it):

```powershell
$env:MODEL_PROVIDER = 'ollama_cloud'
$env:MODEL_BASE_URL = 'https://ollama.com'
$env:MODEL_NAME = '<API model name shown by Ollama>'
$env:OLLAMA_API_KEY = '<your-key>'
$env:MODEL_ALLOW_PHI = 'true'
$env:MODEL_INPUT_USD_PER_1K = '<input dollars per 1,000 tokens>'
$env:MODEL_OUTPUT_USD_PER_1K = '<output dollars per 1,000 tokens>'
$env:MODEL_MAX_COST_USD_PER_CONVERSATION = '0.03'
$env:MODEL_MAX_OUTPUT_TOKENS = '300'
python -m agent chat --tenant plan_a --member M749817 --show-trace
```

The cost adapter counts Ollama's reported prompt and completion tokens using those rates. Ollama publishes rates per million tokens, so divide each current price by 1,000 for these environment variables. The per-conversation cap is an estimate for model charges, not a guarantee against provider billing differences; review Ollama's own usage meter too. Requests contain the grounded answer and may therefore include member-linked benefit/claim information. Set `MODEL_ALLOW_PHI=true` only after verifying the endpoint is allowed for the data. See Ollama's [Cloud API instructions](https://docs.ollama.com/cloud) for key setup and model names.

## Hosted OpenAI-compatible model (optional)

Only configure a hosted endpoint if it is approved to receive member-linked answer text and you have credentials and current pricing for the selected model:

```powershell
$env:MODEL_PROVIDER = 'openai_compatible'
$env:MODEL_BASE_URL = 'https://api.openai.com/v1'
$env:MODEL_NAME = '<approved-model-name>'
$env:MODEL_API_KEY = '<secret-from-your-secret-store>'
$env:MODEL_ALLOW_PHI = 'true'
$env:MODEL_INPUT_USD_PER_1K = '<input-rate>'
$env:MODEL_OUTPUT_USD_PER_1K = '<output-rate>'
$env:MODEL_MAX_COST_USD_PER_CONVERSATION = '0.03'
$env:MODEL_MAX_OUTPUT_TOKENS = '300'
```

The estimated hosted-model cost is capped per conversation; this covers model charges only, not local or cloud infrastructure. No external model credentials or approval were provided for the assessment, so the recorded evaluation did not use a hosted model. `QUESTION_TIMEOUT_SECONDS` defaults to 12 seconds, and the gateway allows up to 24 tool steps across a conversation.
Other configuration: `MEMBER_API_URL` (default `http://127.0.0.1:8090`) sets the mock API URL; `PACK_DIR` sets the pack root containing `kb/` and `mock_services/data/`.

## Tests and evaluation

```powershell
python -m unittest discover -s tests -v
```

With a fresh mock process running in another terminal, execute the 40-case suite and 90% regression gate:

```powershell
python -m eval.run --report eval/report.json --gate
```

The report records case scores, latencies, tool counts, and answers. Four source/fixture conflicts are explained in `NOTES.md` and `doc/ASSESSMENT_PROGRESS.md`; the implementation preserves tenant and source boundaries.

See `doc/HOW_TO_TEST.md` for detailed step-by-step tests and examples. See `doc/ARCHITECTURE.md` for the AWS production design and Azure portability mapping, and `doc/ARCHITECTURE_INTERVIEW_GUIDE.md` for walkthrough and interview preparation.
