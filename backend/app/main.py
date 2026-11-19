"""The API's entry point. Run locally with: uv run fastapi dev app/main.py"""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Adaptive Student Planner API")


class Health(BaseModel):
    status: str


@app.get("/health")
def health() -> Health:
    """Confirms the server is running. Used by tests and, later, by hosting."""
    return Health(status="ok")
