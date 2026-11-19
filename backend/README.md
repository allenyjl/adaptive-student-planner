# Backend

Status: **Proposed**, on branch `feat/backend-fastapi`. The team has not chosen the backend
yet ([question 4](../plan/questions.md)); this is a skeleton to review, not a decision.

A FastAPI server. So far it has one endpoint, `/health`, which confirms the server runs.
There is no database, no accounts, and no connection to the web app yet.

## Setup

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer.

```bash
cd backend
uv sync
```

## Run it

```bash
uv run fastapi dev app/main.py
```

Then open <http://127.0.0.1:8000/health> (should show `{"status":"ok"}`) or
<http://127.0.0.1:8000/docs> for the interactive API page.

## Check it

From the repository root, `./scripts/check.sh` runs lint (ruff), type checks (mypy), and
tests (pytest) for the backend along with the web app. For the backend alone:

```bash
uv run ruff check . && uv run mypy app && uv run pytest
```

## Layout

```
app/main.py           the server and its endpoints
tests/test_health.py  one test per endpoint, so far
pyproject.toml        dependencies and tool settings
uv.lock               exact dependency versions (commit this; do not edit by hand)
```
