"""Tests for the task endpoints, using the web app's own sample tasks as input."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_TASKS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "sample_state.json").read_text()
)["tasks"]

client = TestClient(app)


def test_no_tasks_at_first() -> None:
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_creating_a_task_returns_it_unchanged() -> None:
    task = SAMPLE_TASKS[0]
    response = client.post("/tasks", json=task)
    assert response.status_code == 201
    assert response.json() == task


def test_created_tasks_are_listed_in_the_order_added() -> None:
    for task in SAMPLE_TASKS:
        assert client.post("/tasks", json=task).status_code == 201
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == SAMPLE_TASKS


def test_the_same_id_cannot_be_created_twice() -> None:
    task = SAMPLE_TASKS[0]
    assert client.post("/tasks", json=task).status_code == 201
    again = client.post("/tasks", json=task)
    assert again.status_code == 409
    assert task["id"] in again.json()["detail"]
    assert len(client.get("/tasks").json()) == 1


def test_a_bad_task_is_refused_and_not_saved() -> None:
    bad = {**SAMPLE_TASKS[0], "needMin": -5}
    response = client.post("/tasks", json=bad)
    assert response.status_code == 422
    # The error names the field, so the web app can show what is wrong.
    assert response.json()["detail"][0]["loc"] == ["body", "needMin"]
    assert client.get("/tasks").json() == []


# ---------- PATCH /tasks/{id} ----------


def saved_task() -> dict[str, Any]:
    """Save the first sample task and return it."""
    task = SAMPLE_TASKS[0]
    assert client.post("/tasks", json=task).status_code == 201
    return task


def test_updating_changes_only_the_fields_sent() -> None:
    task = saved_task()
    response = client.patch(f"/tasks/{task['id']}", json={"title": "Renamed", "needMin": 95})
    assert response.status_code == 200
    assert response.json() == {**task, "title": "Renamed", "needMin": 95}
    # The change is saved, not just echoed back.
    assert client.get("/tasks").json() == [{**task, "title": "Renamed", "needMin": 95}]


def test_updating_with_null_clears_a_field() -> None:
    task = saved_task()
    assert task["completeBy"] is not None
    response = client.patch(f"/tasks/{task['id']}", json={"completeBy": None})
    assert response.status_code == 200
    assert response.json()["completeBy"] is None


def test_updating_keeps_the_tasks_place_in_the_list() -> None:
    for task in SAMPLE_TASKS[:3]:
        client.post("/tasks", json=task)
    client.patch(f"/tasks/{SAMPLE_TASKS[1]['id']}", json={"title": "Renamed"})
    assert [t["id"] for t in client.get("/tasks").json()] == [t["id"] for t in SAMPLE_TASKS[:3]]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"needMin": -5}, "needMin"),  # still checked like a new task
        ({"title": None}, "title"),  # a required field cannot be cleared
        ({"notAField": 1}, "notAField"),  # misspelled fields are caught
    ],
    ids=["negative", "cleared-required", "unknown-field"],
)
def test_a_bad_update_is_refused_and_changes_nothing(changes: dict[str, Any], field: str) -> None:
    task = saved_task()
    response = client.patch(f"/tasks/{task['id']}", json=changes)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert client.get("/tasks").json() == [task]


def test_a_tasks_id_cannot_be_changed() -> None:
    task = saved_task()
    response = client.patch(f"/tasks/{task['id']}", json={"id": "something-else"})
    assert response.status_code == 422
    assert client.get("/tasks").json() == [task]


def test_updating_a_missing_task_is_not_found() -> None:
    response = client.patch("/tasks/no-such-task", json={"title": "Renamed"})
    assert response.status_code == 404


# ---------- DELETE /tasks/{id} ----------


def test_deleting_removes_only_that_task() -> None:
    for task in SAMPLE_TASKS[:3]:
        client.post("/tasks", json=task)
    response = client.delete(f"/tasks/{SAMPLE_TASKS[1]['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/tasks").json() == [SAMPLE_TASKS[0], SAMPLE_TASKS[2]]


def test_deleting_a_missing_task_is_not_found() -> None:
    assert client.delete("/tasks/no-such-task").status_code == 404


def test_a_deleted_tasks_id_can_be_used_again() -> None:
    task = saved_task()
    assert client.delete(f"/tasks/{task['id']}").status_code == 204
    assert client.post("/tasks", json=task).status_code == 201
