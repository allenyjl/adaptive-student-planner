# Backend

Status: **Proposed**, on branch `feat/backend-fastapi`. The team has not chosen the backend
yet ([question 4](../plan/questions.md)); this is a skeleton to review, not a decision.

A FastAPI server. There is no database and no accounts yet. The web app can save to it when
switched on; see [web/README.md](../web/README.md#save-to-the-backend-optional-proposed).

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Confirms the server runs |
| `POST /tasks` | Saves a new task (the `Task` shape in `app/models.py`) |
| `GET /tasks` | Lists every saved task, oldest first |
| `PATCH /tasks/{id}` | Changes some fields of a task; send only the fields that change |
| `DELETE /tasks/{id}` | Deletes a task and every calendar block that belongs to it |
| `POST /blocks` | Saves a new calendar block (the `Block` shape); its task, if it has one, must exist |
| `GET /blocks` | Lists every saved calendar block, oldest first |
| `PATCH /blocks/{id}` | Changes some fields of a block, for example its times or its state |
| `DELETE /blocks/{id}` | Deletes one calendar block |
| `GET /prefs` | The student's saved preferences; 404 until some are saved |
| `PUT /prefs` | Saves the preferences, replacing any saved before (the `Prefs` shape) |
| `GET /sync` | Everything the server holds, in one answer, with a `storeId` that changes when the data is lost |
| `POST /sync` | Applies many changes together (tasks, blocks, preferences): all of them, or none. Safe to retry |

Tasks, blocks, and preferences are kept in memory for now: they are lost when the server
restarts, and every caller sees the same ones. The web app's scheduling engine still decides where
sessions go; the server stores what it decided.

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
app/models.py         the data shapes, mirroring web/src/domain/types.ts
app/store.py          where data is kept (in memory, until a database is chosen)
tests/                tests for the endpoints and the models
tests/fixtures/       the web app's own sample data, used as test input
pyproject.toml        dependencies and tool settings
uv.lock               exact dependency versions (commit this; do not edit by hand)
```
