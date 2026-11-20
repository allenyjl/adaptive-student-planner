"""Tests for the preferences endpoints, using the web app's own default preferences."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

PREFS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "sample_state.json").read_text()
)["prefs"]

client = TestClient(app)


def test_no_preferences_at_first() -> None:
    assert client.get("/prefs").status_code == 404


def test_saving_preferences_returns_them_unchanged() -> None:
    response = client.put("/prefs", json=PREFS)
    assert response.status_code == 200
    assert response.json() == PREFS


def test_saved_preferences_can_be_read_back() -> None:
    client.put("/prefs", json=PREFS)
    response = client.get("/prefs")
    assert response.status_code == 200
    assert response.json() == PREFS


def test_saving_again_replaces_the_earlier_preferences() -> None:
    client.put("/prefs", json=PREFS)
    night_owl = {**PREFS, "workStart": "22:00", "workEnd": "03:00", "energy": "evening"}
    assert client.put("/prefs", json=night_owl).status_code == 200
    assert client.get("/prefs").json() == night_owl


def test_saving_the_same_preferences_twice_is_harmless() -> None:
    assert client.put("/prefs", json=PREFS).status_code == 200
    assert client.put("/prefs", json=PREFS).status_code == 200
    assert client.get("/prefs").json() == PREFS


def without(field: str) -> dict[str, Any]:
    return {k: v for k, v in PREFS.items() if k != field}


@pytest.mark.parametrize(
    "bad",
    [
        {**PREFS, "workStart": "9am"},  # not an HH:MM time
        {**PREFS, "energy": "night"},  # not morning, afternoon, or evening
        {**PREFS, "bufferDays": -1},  # never negative
        {**PREFS, "minSession": 60, "sessionMin": 50},  # shortest is longer than preferred
        {**PREFS, "maxSession": 40, "sessionMin": 50},  # longest is shorter than preferred
        {**PREFS, "minSession": 0},  # a session has to last some time
        without("breakMin"),  # every field is required
        {**PREFS, "notAField": 1},  # misspelled fields are caught
    ],
    ids=[
        "bad-clock", "unknown-energy", "negative-buffer", "min-over-preferred",
        "max-under-preferred", "zero-session", "missing-field", "unknown-field",
    ],
)  # fmt: skip
def test_bad_preferences_are_refused_and_change_nothing(bad: dict[str, Any]) -> None:
    client.put("/prefs", json=PREFS)
    assert client.put("/prefs", json=bad).status_code == 422
    assert client.get("/prefs").json() == PREFS
