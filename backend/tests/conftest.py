"""Setup shared by every test file."""

from collections.abc import Iterator

import pytest

from app.store import get_block_store, get_prefs_store, get_task_store


@pytest.fixture(autouse=True)
def empty_stores() -> Iterator[None]:
    """Every test starts and ends with nothing saved."""
    stores = (get_task_store(), get_block_store(), get_prefs_store())
    for store in stores:
        store.clear()
    yield
    for store in stores:
        store.clear()
