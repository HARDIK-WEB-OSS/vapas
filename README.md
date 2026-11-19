# VAPAS

Verified Automated Payment Audit System ("vapas" is Hindi for "money back").

VAPAS reads a person's bank statements, finds refunds the bank reversed late, and calculates the compensation the RBI requires the bank to pay for the delay, citing the exact rule. It never connects to a bank, never moves money and never files anything for the user. It is not legal advice.

Work in progress. Design: [docs/system_design.md](docs/system_design.md) and [docs/adr/](docs/adr/).

## Run locally (Windows PowerShell)

Requirements: Docker Desktop, [uv](https://docs.astral.sh/uv/), Node.js 24.

```powershell
Copy-Item .env.example .env
docker compose up -d --build --wait
Invoke-RestMethod http://127.0.0.1:8000/ready
```

Backend checks:

```powershell
cd backend
uv sync --locked
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
uv run pytest -m integration
cd ..
uv run --project backend python rules/schema.py
```

Frontend:

```powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
npm run test:e2e
```

Local services: API on 127.0.0.1:8000, Postgres on 127.0.0.1:55433, Redis on 127.0.0.1:6379, S3-compatible object storage (SeaweedFS) on 127.0.0.1:8333.

## Real statements

Real statements never enter this repository. They live in the folder named by `PRIVATE_FIXTURES_DIR`, and the app refuses to start if that folder is inside the repository. Committed tests use synthetic statements only.
