"""Where tasks, calendar blocks, and preferences are kept.

TEMPORARY: everything lives in the server's memory, so it is lost when the server restarts
and is shared by everyone who calls the API. This stands in for a database until the team
chooses one. The endpoints only use the methods below, so swapping in a database later
means rewriting this file, not the endpoints.
"""

from collections.abc import Callable
from typing import Protocol
from uuid import uuid4

from app.models import Block, Prefs, Task


class HasId(Protocol):
    """Anything with an id, which is all a Store needs to know about what it holds."""

    @property
    def id(self) -> str: ...


class DuplicateIdError(Exception):
    """Raised when an item is added with an id that is already in use."""


class NotFoundError(Exception):
    """Raised when no item has the given id."""


class Store[T: HasId]:
    """Holds items of one kind (tasks, or blocks), in the order they were added."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}  # id -> item

    def add(self, item: T) -> T:
        """Save a new item. Each id can be used once."""
        if item.id in self._items:
            raise DuplicateIdError(item.id)
        self._items[item.id] = item
        return item

    def save(self, item: T) -> T:
        """Add the item, or replace the saved one with the same id.

        Unlike add(), this never fails, and doing it twice gives the same result as once.
        A replaced item keeps its place in the list.
        """
        self._items[item.id] = item
        return item

    def list(self) -> list[T]:
        """Every saved item, oldest first."""
        return list(self._items.values())

    def has(self, item_id: str) -> bool:
        """Whether an item with this id is saved."""
        return item_id in self._items

    def get(self, item_id: str) -> T:
        """The item with this id."""
        if item_id not in self._items:
            raise NotFoundError(item_id)
        return self._items[item_id]

    def replace(self, item: T) -> T:
        """Save a changed version of an existing item. It keeps its place in the list."""
        if item.id not in self._items:
            raise NotFoundError(item.id)
        self._items[item.id] = item
        return item

    def remove(self, item_id: str) -> None:
        """Delete the item with this id."""
        if item_id not in self._items:
            raise NotFoundError(item_id)
        del self._items[item_id]

    def discard(self, item_id: str) -> bool:
        """Delete the item with this id if there is one. Returns whether there was."""
        return self._items.pop(item_id, None) is not None

    def remove_where(self, matches: Callable[[T], bool]) -> int:
        """Delete every item the test function says yes to. Returns how many were deleted."""
        gone = [item_id for item_id, item in self._items.items() if matches(item)]
        for item_id in gone:
            del self._items[item_id]
        return len(gone)

    def clear(self) -> None:
        """Remove everything. Used by tests so each one starts empty."""
        self._items.clear()


class PrefsStore:
    """Holds the student's preferences: one set, or none if they have not saved any yet."""

    def __init__(self) -> None:
        self._prefs: Prefs | None = None

    def get(self) -> Prefs | None:
        """The saved preferences, or None if nothing has been saved."""
        return self._prefs

    def set(self, prefs: Prefs) -> Prefs:
        """Save the preferences, replacing any saved before."""
        self._prefs = prefs
        return prefs

    def clear(self) -> None:
        """Forget the preferences. Used by tests so each one starts empty."""
        self._prefs = None


# The stores the running server uses.
_task_store: Store[Task] = Store()
_block_store: Store[Block] = Store()
_prefs_store = PrefsStore()


def get_task_store() -> Store[Task]:
    """Gives an endpoint the task store. FastAPI calls this for each request."""
    return _task_store


def get_block_store() -> Store[Block]:
    """Gives an endpoint the block store. FastAPI calls this for each request."""
    return _block_store


def get_prefs_store() -> PrefsStore:
    """Gives an endpoint the preferences store. FastAPI calls this for each request."""
    return _prefs_store


# Identifies this copy of the data. It is made new each time the server starts, which is
# also each time the in-memory data is lost. The web app remembers it: if it changes, the
# web app knows the server no longer has what it sent before, and sends everything again.
# With a database it would stay the same for the database's whole life.
_store_id = uuid4().hex


def get_store_id() -> str:
    """Gives an endpoint the id of the current data. FastAPI calls this for each request."""
    return _store_id
