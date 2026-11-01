# Personal AI Team Platform (M0)

Local-first, provider-agnostic foundation. No agents implemented yet.

## Run tests
python -m unittest discover -s tests -v

## Offline smoke
PAT_AI_PROVIDER=ollama python -m unittest tests.test_offline -v
EOF