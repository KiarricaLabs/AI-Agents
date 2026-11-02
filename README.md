# Personal AI Team

Local-first, offline-capable multi-agent platform. Six agents — Tutor,
Strategist, Executive Assistant, Communications, Soundboard, and Workspace
Architect — run against your local Ollama model. There is no cloud provider
and no silent cloud fallback.

## Quick start

Full instructions are in [docs/run.md](docs/run.md).

Prerequisites:

- Python 3.11+ (use the project virtualenv)
- Ollama running locally with a model pulled (default `llama3.1`):

  ```bash
  ollama pull llama3.1
  ```

Start the backend (defaults to http://127.0.0.1:8001):

```bash
uvicorn api.app:app --host 127.0.0.1 --port 8001
```

Start the frontend (http://localhost:5173):

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173, open the **Agents** tab, select an agent, enter a
task, and press **Run**.

## Configuration

Environment variables are documented in [docs/run.md](docs/run.md). The
important ones are `PAT_AI_PROVIDER` (default `ollama`), `PAT_AI_MODEL`
(default `llama3.1`), and `PAT_AI_BASE_URL` (default `http://localhost:11434`).

## Running tests

```bash
# Backend (unittest, isolated temp DB)
python -m unittest discover -s tests -t . -v

# Live Ollama smoke test (skipped automatically when Ollama is down)
python -m unittest tests.test_m8_live -v

# Frontend component tests
cd frontend && npx vitest run

# End-to-end (isolated test DB; frontend must be running on 5173, port 8001 free)
cd frontend && npx playwright test
```

## Notes

- Local development identity is enabled by default (`PAT_LOCAL_MODE=1`),
  which runs unauthenticated requests as the trusted, configured local user.
  Set `PAT_LOCAL_MODE=0` to require a server-verified JWT passed via the
  `x-token` header (fail-closed).
- The original Social Media Manager is a separate project and is not part of
  this repository.
