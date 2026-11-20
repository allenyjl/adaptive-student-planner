"""Tests for /sync: GET reads everything at once; POST applies many changes, all or none."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.store import get_store_id

SAMPLE: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "sample_state.json").read_text()
)
TASKS: list[dict[str, Any]] = SAMPLE["tasks"]
BLOCKS: list[dict[str, Any]] = SAMPLE["blocks"]
PREFS: dict[str, Any] = SAMPLE["prefs"]
EVENTS = [b for b in BLOCKS if "taskId" not in b]  # belong to no task
SESSIONS = [b for b in BLOCKS if "taskId" in b]  # each belongs to a task

client = TestClient(app)


def everything() -> dict[str, Any]:
    """What the server currently holds."""
    prefs = client.get("/prefs")
    return {
        "tasks": client.get("/tasks").json(),
        "blocks": client.get("/blocks").json(),
        "prefs": prefs.json() if prefs.status_code == 200 else None,
    }


def save_whole_sample() -> None:
    response = client.post(
        "/sync", json={"tasks": {"save": TASKS}, "blocks": {"save": BLOCKS}, "prefs": PREFS}
    )
    assert response.status_code == 200


def sessions_of(task_id: str) -> list[dict[str, Any]]:
    return [b for b in SESSIONS if b["taskId"] == task_id]


# ---------- Saving ----------


def test_the_whole_sample_saves_in_one_request() -> None:
    response = client.post(
        "/sync", json={"tasks": {"save": TASKS}, "blocks": {"save": BLOCKS}, "prefs": PREFS}
    )
    assert response.status_code == 200
    assert response.json() == {
        "tasksSaved": len(TASKS), "tasksDeleted": 0,
        "blocksSaved": len(BLOCKS), "blocksDeleted": 0, "prefsSaved": True,
        "storeId": get_store_id(),
    }  # fmt: skip
    assert everything() == {"tasks": TASKS, "blocks": BLOCKS, "prefs": PREFS}


def test_an_empty_request_changes_nothing() -> None:
    save_whole_sample()
    response = client.post("/sync", json={})
    assert response.status_code == 200
    assert response.json()["prefsSaved"] is False
    assert everything() == {"tasks": TASKS, "blocks": BLOCKS, "prefs": PREFS}


def test_a_new_task_and_its_sessions_save_together() -> None:
    """The case this endpoint exists for: adding a task creates the task and its sessions."""
    task = TASKS[0]
    its_sessions = sessions_of(task["id"])
    assert its_sessions
    response = client.post(
        "/sync", json={"tasks": {"save": [task]}, "blocks": {"save": its_sessions}}
    )
    assert response.status_code == 200
    assert everything() == {"tasks": [task], "blocks": its_sessions, "prefs": None}


def test_saving_an_existing_item_replaces_it_in_place() -> None:
    save_whole_sample()
    renamed = {**TASKS[1], "title": "Renamed"}
    moved = {**EVENTS[0], "start": EVENTS[0]["start"] + 60_000, "end": EVENTS[0]["end"] + 60_000}
    response = client.post(
        "/sync", json={"tasks": {"save": [renamed]}, "blocks": {"save": [moved]}}
    )
    assert response.status_code == 200
    now = everything()
    assert now["tasks"] == [renamed if t["id"] == renamed["id"] else t for t in TASKS]
    assert now["blocks"] == [moved if b["id"] == moved["id"] else b for b in BLOCKS]


# ---------- Deleting ----------


def test_deleting_blocks_leaves_everything_else() -> None:
    save_whole_sample()
    gone = [EVENTS[0]["id"], SESSIONS[0]["id"]]
    response = client.post("/sync", json={"blocks": {"delete": gone}})
    assert response.status_code == 200
    assert response.json()["blocksDeleted"] == 2
    now = everything()
    assert now["blocks"] == [b for b in BLOCKS if b["id"] not in gone]
    assert now["tasks"] == TASKS


def test_deleting_a_task_removes_its_blocks_and_no_others() -> None:
    save_whole_sample()
    task_id = SESSIONS[0]["taskId"]
    response = client.post("/sync", json={"tasks": {"delete": [task_id]}})
    assert response.status_code == 200
    assert response.json()["tasksDeleted"] == 1
    assert response.json()["blocksDeleted"] == len(sessions_of(task_id))
    now = everything()
    assert now["tasks"] == [t for t in TASKS if t["id"] != task_id]
    assert now["blocks"] == [b for b in BLOCKS if b.get("taskId") != task_id]


def test_deleting_two_tasks_removes_each_ones_blocks() -> None:
    save_whole_sample()
    ids = sorted({b["taskId"] for b in SESSIONS})[:2]
    assert len(ids) == 2
    assert client.post("/sync", json={"tasks": {"delete": ids}}).status_code == 200
    assert everything()["blocks"] == [b for b in BLOCKS if b.get("taskId") not in ids]


def test_one_request_can_replace_a_tasks_sessions() -> None:
    """Rescheduling: the old sessions go and new ones arrive in the same request."""
    save_whole_sample()
    old = sessions_of(SESSIONS[0]["taskId"])
    new = [
        {**b, "id": b["id"] + "-new", "start": b["start"] + 60_000, "end": b["end"] + 60_000}
        for b in old
    ]
    response = client.post(
        "/sync", json={"blocks": {"delete": [b["id"] for b in old], "save": new}}
    )
    assert response.status_code == 200
    old_ids = {b["id"] for b in old}
    assert everything()["blocks"] == [b for b in BLOCKS if b["id"] not in old_ids] + new


# ---------- Safe to retry ----------


def test_sending_the_same_changes_twice_gives_the_same_result() -> None:
    save_whole_sample()
    changes = {
        "tasks": {"save": [{**TASKS[0], "title": "Renamed"}], "delete": [TASKS[1]["id"]]},
        "blocks": {"delete": [EVENTS[0]["id"]]},
        "prefs": {**PREFS, "energy": "evening"},
    }
    assert client.post("/sync", json=changes).status_code == 200
    after_once = everything()
    again = client.post("/sync", json=changes)
    assert again.status_code == 200
    assert again.json()["tasksDeleted"] == 0  # already gone, and that is not an error
    assert everything() == after_once


# ---------- All or nothing ----------


def assert_refused_and_nothing_changed(changes: dict[str, Any], loc: list[Any]) -> None:
    save_whole_sample()
    before = everything()
    response = client.post("/sync", json=changes)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == loc
    assert everything() == before


def test_one_bad_item_stops_every_change() -> None:
    """A valid rename, a valid delete, and new preferences all ride with one bad block."""
    assert_refused_and_nothing_changed(
        {
            "tasks": {"save": [{**TASKS[0], "title": "Renamed"}], "delete": [TASKS[1]["id"]]},
            "blocks": {"save": [EVENTS[0], {**EVENTS[1], "end": EVENTS[1]["start"]}]},
            "prefs": {**PREFS, "energy": "evening"},
        },
        ["body", "blocks", "save", 1],
    )


def test_a_session_for_a_task_that_does_not_exist_stops_every_change() -> None:
    assert_refused_and_nothing_changed(
        {
            "tasks": {"save": [{**TASKS[0], "title": "Renamed"}]},
            "blocks": {"save": [{**SESSIONS[0], "id": "new", "taskId": "no-such-task"}]},
        },
        ["body", "blocks", "save", 0, "taskId"],
    )


def test_a_session_for_a_task_deleted_in_the_same_request_stops_every_change() -> None:
    session = SESSIONS[0]
    assert_refused_and_nothing_changed(
        {
            "tasks": {"delete": [session["taskId"]]},
            "blocks": {"save": [{**session, "id": "new"}]},
        },
        ["body", "blocks", "save", 0, "taskId"],
    )


def test_saving_and_deleting_the_same_item_stops_every_change() -> None:
    assert_refused_and_nothing_changed(
        {"tasks": {"save": [TASKS[0]], "delete": [TASKS[0]["id"]]}},
        ["body", "tasks", "save", 0, "id"],
    )


def test_bad_preferences_stop_every_change() -> None:
    assert_refused_and_nothing_changed(
        {"tasks": {"delete": [TASKS[0]["id"]]}, "prefs": {**PREFS, "workStart": "9am"}},
        ["body", "prefs", "workStart"],
    )


# ---------- GET /sync: reading everything ----------


def test_an_empty_server_reads_as_empty() -> None:
    response = client.get("/sync")
    assert response.status_code == 200
    assert response.json() == {"storeId": get_store_id(), "tasks": [], "blocks": [], "prefs": None}


def test_everything_saved_is_read_back_in_one_answer() -> None:
    save_whole_sample()
    response = client.get("/sync")
    assert response.status_code == 200
    assert response.json() == {
        "storeId": get_store_id(), "tasks": TASKS, "blocks": BLOCKS, "prefs": PREFS,
    }  # fmt: skip


def test_reading_and_saving_report_the_same_store_id() -> None:
    read = client.get("/sync").json()["storeId"]
    saved = client.post("/sync", json={}).json()["storeId"]
    assert read == saved
    assert len(read) >= 16  # long enough that two servers never share one by chance


def test_a_restarted_server_has_a_new_store_id() -> None:
    """A restart loses the in-memory data, and the id is how the web app finds out."""
    from uuid import uuid4

    before = client.get("/sync").json()["storeId"]
    app.dependency_overrides[get_store_id] = lambda: uuid4().hex  # what a restart does
    try:
        assert client.get("/sync").json()["storeId"] != before
    finally:
        app.dependency_overrides.clear()
