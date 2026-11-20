"""The API's entry point. Run locally with: uv run fastapi dev app/main.py

Contents, in order:
  1. Shared helpers   used by both the task and the block endpoints
  2. Health           GET /health
  3. Tasks            the to-do list: POST, GET, PATCH, DELETE /tasks
  4. Blocks           the calendar:   POST, GET, PATCH, DELETE /blocks
  5. Preferences      how the student likes to work: GET, PUT /prefs
  6. Sync             everything at once: GET /sync reads it all, POST /sync saves
                      many changes, all or nothing

For tasks and blocks alike, fields the web app left out are left out of the answer too
(response_model_exclude_unset), so an item comes back exactly as it was sent.

NOT YET: there are no accounts, so every caller sees the same data. Each task and block
must belong to one student, checked on the server, before real data is stored.
"""

from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ValidationError

from app.models import ApiModel, Block, ChangeSet, Prefs, Snapshot, SyncResult, Task
from app.store import (
    DuplicateIdError,
    NotFoundError,
    PrefsStore,
    Store,
    get_block_store,
    get_prefs_store,
    get_store_id,
    get_task_store,
)

app = FastAPI(title="Adaptive Student Planner API")

# =============================================================================
# 1. Shared helpers
# =============================================================================

# Shorthand for "this endpoint needs the task store" and "... the block store".
Tasks = Annotated[Store[Task], Depends(get_task_store)]
Blocks = Annotated[Store[Block], Depends(get_block_store)]
SavedPrefs = Annotated[PrefsStore, Depends(get_prefs_store)]
StoreId = Annotated[str, Depends(get_store_id)]

# The body of a PATCH request: only the fields to change.
Changes = Annotated[
    dict[str, Any],
    Body(description="Only the fields to change, named as in the full item."),
]


def not_found(kind: str, item_id: str) -> HTTPException:
    """The error sent when no task (or block) has the given id."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"No {kind} with id '{item_id}'."
    )


def already_exists(kind: str, item_id: str) -> HTTPException:
    """The error sent when an id is already in use."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"A {kind} with id '{item_id}' already exists.",
    )


def invalid(detail: Any) -> HTTPException:
    """The error sent when the data breaks a rule."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def with_changes[T: ApiModel](
    model: type[T], current: T, item_id: str, changes: dict[str, Any]
) -> T:
    """Lay a PATCH's changes over a saved item and check the result like a new item.

    Returns the updated item, or raises the error to send back. Nothing is saved here.
    """
    if changes.get("id", item_id) != item_id:
        raise invalid("An id cannot be changed.")
    merged = {**current.model_dump(by_alias=True, exclude_unset=True), **changes}
    try:
        return model.model_validate(merged)
    except ValidationError as error:
        # Same shape as FastAPI's own errors, so the web app handles one format.
        raise invalid(
            [
                {"type": e["type"], "loc": ["body", *e["loc"]], "msg": e["msg"]}
                for e in error.errors()
            ]
        ) from None


def check_task_exists(block: Block, tasks: Store[Task]) -> None:
    """A block that names a task must name one that exists."""
    if block.task_id is not None and not tasks.has(block.task_id):
        raise invalid(
            [
                {
                    "type": "task_not_found",
                    "loc": ["body", "taskId"],
                    "msg": f"No task with id '{block.task_id}'. Create the task first.",
                }
            ]
        )


# =============================================================================
# 2. Health
# =============================================================================


class Health(BaseModel):
    status: str


@app.get("/health")
def health() -> Health:
    """Confirms the server is running. Used by tests and, later, by hosting."""
    return Health(status="ok")


# =============================================================================
# 3. Tasks: the to-do list
# =============================================================================


@app.post(
    "/tasks",
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_unset=True,
    responses={409: {"description": "A task with this id already exists"}},
)
def create_task(task: Task, tasks: Tasks) -> Task:
    """Save a new task and return it.

    The web app chooses the task's id. Sending the same id twice is refused, so a retry
    after a lost connection cannot create a duplicate.
    """
    try:
        return tasks.add(task)
    except DuplicateIdError:
        raise already_exists("task", task.id) from None


@app.get("/tasks", response_model_exclude_unset=True)
def list_tasks(tasks: Tasks) -> list[Task]:
    """Every saved task, oldest first."""
    return tasks.list()


@app.patch(
    "/tasks/{task_id}",
    response_model_exclude_unset=True,
    responses={
        404: {"description": "No task has this id"},
        422: {"description": "The change would make the task invalid"},
    },
)
def update_task(task_id: str, changes: Changes, tasks: Tasks) -> Task:
    """Change some fields of a task and return the whole updated task.

    Send only the fields that change; the rest stay as they were. Sending null clears a
    field that allows it (for example "completeBy": null removes the deadline). The task
    is checked as a whole after the change, so a change cannot leave it invalid. The id
    cannot be changed.
    """
    try:
        current = tasks.get(task_id)
    except NotFoundError:
        raise not_found("task", task_id) from None
    return tasks.replace(with_changes(Task, current, task_id, changes))


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "No task has this id"}},
)
def delete_task(task_id: str, tasks: Tasks, blocks: Blocks) -> None:
    """Delete a task and every calendar block that belongs to it. Answers with no content.

    Removing the blocks too matches what the web app does, and means a block can never
    point at a task that no longer exists.
    """
    try:
        tasks.remove(task_id)
    except NotFoundError:
        raise not_found("task", task_id) from None
    blocks.remove_where(lambda block: block.task_id == task_id)


# =============================================================================
# 4. Blocks: the calendar
#    The web app's scheduling engine decides where sessions go. These endpoints
#    store what it decided; they do not schedule anything themselves.
# =============================================================================


@app.post(
    "/blocks",
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_unset=True,
    responses={409: {"description": "A block with this id already exists"}},
)
def create_block(block: Block, blocks: Blocks, tasks: Tasks) -> Block:
    """Save a new calendar block and return it.

    If the block belongs to a task (taskId), that task must already be saved. As with
    tasks, the web app chooses the id and the same id cannot be used twice.
    """
    check_task_exists(block, tasks)
    try:
        return blocks.add(block)
    except DuplicateIdError:
        raise already_exists("block", block.id) from None


@app.get("/blocks", response_model_exclude_unset=True)
def list_blocks(blocks: Blocks) -> list[Block]:
    """Every saved calendar block, oldest first."""
    return blocks.list()


@app.patch(
    "/blocks/{block_id}",
    response_model_exclude_unset=True,
    responses={
        404: {"description": "No block has this id"},
        422: {"description": "The change would make the block invalid"},
    },
)
def update_block(block_id: str, changes: Changes, blocks: Blocks, tasks: Tasks) -> Block:
    """Change some fields of a block and return the whole updated block.

    Works like updating a task: send only the fields that change. Moving a block is
    {"start": ..., "end": ...}; marking a session done is {"state": "done"}.
    """
    try:
        current = blocks.get(block_id)
    except NotFoundError:
        raise not_found("block", block_id) from None
    updated = with_changes(Block, current, block_id, changes)
    check_task_exists(updated, tasks)
    return blocks.replace(updated)


@app.delete(
    "/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "No block has this id"}},
)
def delete_block(block_id: str, blocks: Blocks) -> None:
    """Delete one calendar block. Its task, if it has one, is not touched."""
    try:
        blocks.remove(block_id)
    except NotFoundError:
        raise not_found("block", block_id) from None


# =============================================================================
# 5. Preferences: how the student likes to work
#    There is one set of preferences, so these endpoints take no id. Temporary
#    relaxations (Override in models.py) are separate and have no endpoints yet.
# =============================================================================


@app.get(
    "/prefs",
    responses={404: {"description": "No preferences have been saved yet"}},
)
def get_prefs(saved: SavedPrefs) -> Prefs:
    """The student's saved preferences.

    Answers 404 until preferences are saved for the first time. The server does not make
    up defaults: which defaults to use is still an open team question (question 8 in
    plan/questions.md), and the web app already has placeholder ones. On a 404 the web
    app should use its own defaults and save them here once the student confirms them.
    """
    prefs = saved.get()
    if prefs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No preferences have been saved yet."
        )
    return prefs


@app.put("/prefs")
def save_prefs(prefs: Prefs, saved: SavedPrefs) -> Prefs:
    """Save the student's preferences and return them.

    Send every field: this replaces the saved preferences as a whole. Saving the same
    preferences twice is harmless, so the web app can safely retry.

    Changing preferences does not move anything already on the calendar, which matches
    the web app.
    """
    return saved.set(prefs)


# =============================================================================
# 6. Sync: many changes at once, all or nothing
#    The endpoints above change one thing each. One action in the web app often
#    changes several, and sending them one by one could leave half of a change
#    saved if a request failed partway. This endpoint takes them together.
# =============================================================================


def check_change_set(changes: ChangeSet, tasks: Store[Task]) -> None:
    """Refuse a change set that contradicts itself or would leave a block without its task.

    Raises the error to send back. Runs before anything is saved.
    """
    problems: list[dict[str, Any]] = []

    # The same item cannot be both saved and deleted in one change set.
    saves_and_deletes: list[tuple[str, list[str], set[str]]] = [
        ("tasks", [task.id for task in changes.tasks.save], set(changes.tasks.delete)),
        ("blocks", [block.id for block in changes.blocks.save], set(changes.blocks.delete)),
    ]
    for kind, saved_ids, deleted_ids in saves_and_deletes:
        for index, item_id in enumerate(saved_ids):
            if item_id in deleted_ids:
                problems.append(
                    {
                        "type": "save_and_delete",
                        "loc": ["body", kind, "save", index, "id"],
                        "msg": f"'{item_id}' is both saved and deleted in the same request.",
                    }
                )

    # Every saved block that names a task needs that task to exist afterwards:
    # either saved here, or saved earlier and not deleted here.
    saved_here = {task.id for task in changes.tasks.save}
    deleted_here = set(changes.tasks.delete)
    for index, block in enumerate(changes.blocks.save):
        task_id = block.task_id
        if task_id is None or task_id in saved_here:
            continue
        if task_id in deleted_here or not tasks.has(task_id):
            problems.append(
                {
                    "type": "task_not_found",
                    "loc": ["body", "blocks", "save", index, "taskId"],
                    "msg": f"No task with id '{task_id}' would exist after these changes.",
                }
            )

    if problems:
        raise invalid(problems)


@app.get("/sync", response_model_exclude_unset=True)
def read_everything(tasks: Tasks, blocks: Blocks, saved: SavedPrefs, store_id: StoreId) -> Snapshot:
    """Everything the server holds, in one answer: tasks, blocks, and preferences.

    The web app calls this when it starts. One request gives one consistent picture,
    which three separate requests could not if something changed in between.
    """
    return Snapshot(store_id=store_id, tasks=tasks.list(), blocks=blocks.list(), prefs=saved.get())


@app.post(
    "/sync",
    responses={422: {"description": "Something is invalid; nothing was saved"}},
)
def sync(
    changes: ChangeSet, tasks: Tasks, blocks: Blocks, saved: SavedPrefs, store_id: StoreId
) -> SyncResult:
    """Apply many changes together: all of them, or none.

    Send every task and block that is new or changed, in full, under "save", and the ids
    of the ones to delete under "delete". Everything is checked first; if anything is
    wrong, nothing is saved and the answer says what to fix.

    Safe to retry: sending the same changes twice leaves the same result as sending them
    once. Saving replaces an item with the same id, and deleting an id that is already
    gone is not an error.

    Deleting a task also deletes its blocks, as DELETE /tasks/{id} does.
    """
    # 1. Check everything. Nothing has been saved yet, so failing here changes nothing.
    check_change_set(changes, tasks)

    # 2. Apply. No step below can fail.
    blocks_deleted = sum(blocks.discard(block_id) for block_id in changes.blocks.delete)
    tasks_deleted = sum(tasks.discard(task_id) for task_id in changes.tasks.delete)
    deleted_task_ids = set(changes.tasks.delete)
    blocks_deleted += blocks.remove_where(lambda block: block.task_id in deleted_task_ids)
    for task in changes.tasks.save:
        tasks.save(task)
    for block in changes.blocks.save:
        blocks.save(block)
    if changes.prefs is not None:
        saved.set(changes.prefs)

    return SyncResult(
        tasks_saved=len(changes.tasks.save),
        tasks_deleted=tasks_deleted,
        blocks_saved=len(changes.blocks.save),
        blocks_deleted=blocks_deleted,
        prefs_saved=changes.prefs is not None,
        store_id=store_id,
    )
