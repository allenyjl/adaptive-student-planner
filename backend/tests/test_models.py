"""Checks that the models match the web app's data.

tests/fixtures/sample_state.json is the web app's own sample data, written out by
seed() in web/src/state/seed.ts. If these tests fail after a change to
web/src/domain/types.ts, update app/models.py to match and refresh the fixture.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.models import Block, CompletedRecord, Notifications, Prefs, Task

SAMPLE: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "sample_state.json").read_text()
)


def roundtrip(model: type[Any], data: dict[str, Any]) -> dict[str, Any]:
    """Read web-app JSON into a model, then write it back out the way the API would."""
    result: dict[str, Any] = model.model_validate(data).model_dump(
        by_alias=True, exclude_unset=True
    )
    return result


def test_sample_has_data_to_check() -> None:
    assert len(SAMPLE["tasks"]) > 0
    assert len(SAMPLE["blocks"]) > 0


@pytest.mark.parametrize("task", SAMPLE["tasks"], ids=lambda t: t["title"])
def test_every_sample_task_passes_through_unchanged(task: dict[str, Any]) -> None:
    assert roundtrip(Task, task) == task


def test_every_sample_block_passes_through_unchanged() -> None:
    for block in SAMPLE["blocks"]:
        assert roundtrip(Block, block) == block


def test_sample_prefs_and_notifications_pass_through_unchanged() -> None:
    assert roundtrip(Prefs, SAMPLE["prefs"]) == SAMPLE["prefs"]
    assert roundtrip(Notifications, SAMPLE["notifications"]) == SAMPLE["notifications"]


def test_completed_record_uses_the_web_apps_field_names() -> None:
    record = {
        "taskId": "t1", "title": "Problem set 3", "course": "CIS 1600", "type": "assignment",
        "predictedMin": 240, "actualMin": 300, "at": 1790000000000, "sample": False,
    }  # fmt: skip
    assert roundtrip(CompletedRecord, record) == record


def test_python_code_uses_snake_case_names() -> None:
    task = Task.model_validate(SAMPLE["tasks"][0])
    assert task.need_min == SAMPLE["tasks"][0]["needMin"]


def a_task(**changes: Any) -> dict[str, Any]:
    return {**SAMPLE["tasks"][0], **changes}


@pytest.mark.parametrize(
    "bad",
    [
        a_task(needMin=-5),  # durations are never negative
        a_task(needMin=12.5),  # durations are whole minutes
        a_task(type="chore"),  # not one of the known task types
        a_task(dayWindow={"from": "25:00", "to": "26:00"}),  # not a real clock time
        a_task(allowedDays=[7]),  # weekdays are 0 to 6
        a_task(notAField=1),  # unknown fields are rejected, so typos are caught
    ],
    ids=["negative", "fractional", "unknown-type", "bad-clock", "bad-weekday", "unknown-field"],
)
def test_bad_task_data_is_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Task.model_validate(bad)


def test_a_task_missing_a_required_field_is_rejected() -> None:
    task = a_task()
    del task["title"]
    with pytest.raises(ValidationError):
        Task.model_validate(task)
