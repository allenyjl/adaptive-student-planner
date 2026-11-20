"""Tests for the calendar block endpoints, using the web app's own sample data as input."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "sample_state.json").read_text()
)
# Plain calendar events and classes: they belong to no task.
EVENTS: list[dict[str, Any]] = [b for b in SAMPLE["blocks"] if "taskId" not in b]
# Work sessions: each belongs to a task.
SESSIONS: list[dict[str, Any]] = [b for b in SAMPLE["blocks"] if "taskId" in b]

client = TestClient(app)


def task_of(session: dict[str, Any]) -> dict[str, Any]:
    """The sample task a session belongs to."""
    task: dict[str, Any] = next(t for t in SAMPLE["tasks"] if t["id"] == session["taskId"])
    return task


def saved_session() -> dict[str, Any]:
    """Save the first sample session, and the task it belongs to, and return the session."""
    session = SESSIONS[0]
    assert client.post("/tasks", json=task_of(session)).status_code == 201
    assert client.post("/blocks", json=session).status_code == 201
    return session


def test_the_sample_has_both_kinds_of_block() -> None:
    assert len(EVENTS) > 0
    assert len(SESSIONS) > 0


# ---------- POST and GET /blocks ----------


def test_no_blocks_at_first() -> None:
    response = client.get("/blocks")
    assert response.status_code == 200
    assert response.json() == []


def test_creating_an_event_returns_it_unchanged() -> None:
    response = client.post("/blocks", json=EVENTS[0])
    assert response.status_code == 201
    assert response.json() == EVENTS[0]


def test_the_whole_sample_calendar_can_be_saved_and_listed() -> None:
    for task in SAMPLE["tasks"]:
        assert client.post("/tasks", json=task).status_code == 201
    for block in SAMPLE["blocks"]:
        assert client.post("/blocks", json=block).status_code == 201
    assert client.get("/blocks").json() == SAMPLE["blocks"]


def test_the_same_id_cannot_be_created_twice() -> None:
    assert client.post("/blocks", json=EVENTS[0]).status_code == 201
    assert client.post("/blocks", json=EVENTS[0]).status_code == 409
    assert len(client.get("/blocks").json()) == 1


def test_a_session_needs_its_task_to_exist_first() -> None:
    response = client.post("/blocks", json=SESSIONS[0])
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "taskId"]
    assert client.get("/blocks").json() == []


@pytest.mark.parametrize(
    "bad",
    [
        {**EVENTS[0], "end": EVENTS[0]["start"]},  # no length
        {**EVENTS[0], "end": EVENTS[0]["start"] - 60_000},  # ends before it starts
        {**EVENTS[0], "state": "cancelled"},  # not a known state
        {**EVENTS[0], "notAField": 1},  # misspelled fields are caught
    ],
    ids=["zero-length", "backwards", "unknown-state", "unknown-field"],
)
def test_a_bad_block_is_refused_and_not_saved(bad: dict[str, Any]) -> None:
    assert client.post("/blocks", json=bad).status_code == 422
    assert client.get("/blocks").json() == []


# ---------- PATCH /blocks/{id} ----------


def test_moving_a_block_changes_only_its_times() -> None:
    event = EVENTS[0]
    client.post("/blocks", json=event)
    later = {"start": event["start"] + 3_600_000, "end": event["end"] + 3_600_000}
    response = client.patch(f"/blocks/{event['id']}", json=later)
    assert response.status_code == 200
    assert response.json() == {**event, **later}
    assert client.get("/blocks").json() == [{**event, **later}]


def test_a_session_can_be_marked_done_with_its_actual_time() -> None:
    session = saved_session()
    response = client.patch(f"/blocks/{session['id']}", json={"state": "done", "actualMin": 45})
    assert response.status_code == 200
    assert response.json() == {**session, "state": "done", "actualMin": 45}


@pytest.mark.parametrize(
    "changes",
    [
        {"end": 0},  # would end before it starts
        {"taskId": "no-such-task"},  # would point at a task that does not exist
        {"id": "something-else"},  # an id cannot be changed
        {"title": None},  # a required field cannot be cleared
    ],
    ids=["backwards", "missing-task", "new-id", "cleared-required"],
)
def test_a_bad_update_is_refused_and_changes_nothing(changes: dict[str, Any]) -> None:
    session = saved_session()
    assert client.patch(f"/blocks/{session['id']}", json=changes).status_code == 422
    assert client.get("/blocks").json() == [session]


def test_updating_a_missing_block_is_not_found() -> None:
    assert client.patch("/blocks/no-such-block", json={"title": "Renamed"}).status_code == 404


# ---------- DELETE /blocks/{id} ----------


def test_deleting_removes_only_that_block() -> None:
    for event in EVENTS[:3]:
        client.post("/blocks", json=event)
    response = client.delete(f"/blocks/{EVENTS[1]['id']}")
    assert response.status_code == 204
    assert client.get("/blocks").json() == [EVENTS[0], EVENTS[2]]


def test_deleting_a_session_leaves_its_task() -> None:
    session = saved_session()
    assert client.delete(f"/blocks/{session['id']}").status_code == 204
    assert client.get("/tasks").json() == [task_of(session)]


def test_deleting_a_missing_block_is_not_found() -> None:
    assert client.delete("/blocks/no-such-block").status_code == 404


# ---------- Deleting a task ----------


def test_deleting_a_task_removes_its_blocks_and_no_others() -> None:
    for task in SAMPLE["tasks"]:
        client.post("/tasks", json=task)
    for block in SAMPLE["blocks"]:
        client.post("/blocks", json=block)
    task_id = SESSIONS[0]["taskId"]

    assert client.delete(f"/tasks/{task_id}").status_code == 204

    expected = [b for b in SAMPLE["blocks"] if b.get("taskId") != task_id]
    assert len(expected) < len(SAMPLE["blocks"])
    assert client.get("/blocks").json() == expected
