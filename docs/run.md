# Running the Personal AI Team

This guide covers launching the backend and frontend locally so you can talk
to the six agents through a real local Ollama model.

## Prerequisites

1. **Python 3.11** (the project's virtualenv was created against CPython 3.11;
   a newer system Python may be missing pinned dependencies).
2. **Ollama** installed and running at `http://localhost:11434`, with a model
   pulled. The default model is `llama3.1`:

   ```bash
   ollama pull llama3.1
   ```

   Each agent's `model` spec lives in its `agents/<name>/manifest.json`.

3. **Node.js** for the frontend (Vite + React).

## Backend

From the repository root, in the project virtualenv:

```bash
uvicorn api.app:app --host 127.0.0.1 --port 8001
```

The API base URL used by the frontend is `http://127.0.0.1:8001`.

### Environment variables

| Variable             | Default                       | Purpose                                  |
|----------------------|-------------------------------|------------------------------------------|
| `PAT_DB_PATH`        | `data/pat.db`                 | SQLite database path                     |
| `PAT_AI_PROVIDER`    | `ollama`                      | Model provider (M8 is Ollama-only)       |
| `PAT_AI_MODEL`       | `llama3.1`                    | Default model name                       |
| `PAT_AI_BASE_URL`    | `http://localhost:11434`      | Ollama endpoint                          |
| `PAT_AI_API_KEY`     | ``                            | (Unused in M8 — no cloud provider)       |
| `PAT_MASTER_KEY`     | ``                            | Fernet key for encrypted credentials     |
| `PAT_DEFAULT_TENANT` | `local`                       | Default tenant for local mode            |
| `PAT_LOCAL_MODE`     | `1`                           | `1` = trusted local identity; `0` = fail-closed JWT |
| `PAT_LOCAL_USER`     | `local`                       | Trusted local user id for local mode     |

### Identity model

- **Local development** (`PAT_LOCAL_MODE=1`, the default): requests without a
  token run as the trusted, configured local user (`PAT_LOCAL_USER`) in the
  default tenant (`PAT_DEFAULT_TENANT`). Identity is established server-side;
  there is no trust in client-supplied `user_id`/`tenant_id`.
- **Authenticated** (`PAT_LOCAL_MODE=0`): every protected request must carry a
  server-verified JWT in the `x-token` header. Missing, invalid, or expired
  tokens are rejected (fail-closed).

## Frontend

In `frontend/`:

```bash
npm install
npm run dev
```

Open http://localhost:5173.

### Agents tab

1. Select the **Agents** tab.
2. Choose one of the six agents.
3. Enter a task and press **Run**.
4. The reply, execution location (`local:ollama:...`), any known (approved)
   memory facts, and any pending memory/goal proposals or tool results are
   shown.

In this v1 interactive runtime there is **no automatic tool calling, no
autonomous memory/goal proposals, and no automatic approvals**. Tool calls and
memory/goal proposals only occur when explicitly driven through the request
context; human approval remains explicit.

## Live verification (real Ollama, not mocked)

```bash
python -m unittest tests.test_m8_live -v
```

This runs all six agents through the real `ModelRouter` → Ollama path and is
**skipped automatically** (reported as skipped) when Ollama is unreachable.

## Tests

```bash
# Backend unit + HTTP integration tests
python -m unittest discover -s tests -v

# Frontend component tests
cd frontend && npx vitest run

# End-to-end (backend on 8001 and frontend on 5173 must be running)
cd frontend && npx playwright test
```
