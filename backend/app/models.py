"""The data shapes the API accepts and returns.

These mirror web/src/domain/types.ts, so the web app's data passes through unchanged.
When a type changes there, change it here in the same commit; tests/test_models.py
checks that the web app's own sample data still fits.

Conventions:
- JSON uses the web app's camelCase names (needMin); Python uses snake_case (need_min).
- Timestamps are integer milliseconds since the epoch, which is UTC by definition.
- Durations are integer minutes.
- Clock times ("HH:MM") are wall-clock times in the student's own timezone. That timezone
  is not stored anywhere yet; it has to be added with student profiles.

Contents, in order:
  1. Building blocks      small reusable types (Minutes, Clock, ...)
  2. Preferences          Prefs, Override
  3. Repeats              RepeatEnds, RepeatRule
  4. Parts of a task      Milestone, PredictionEntry, Prediction, Instructions, DayWindow
  5. Task                 one entry on the to-do list
  6. Block                one entry on the calendar
  7. Feedback and history Pending, CompletedRecord
  8. Settings             Notifications
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

# =============================================================================
# 1. Building blocks
#    Small types reused by the models below. Each one adds a rule that is
#    checked automatically whenever data comes in.
# =============================================================================

# A duration in whole minutes, never negative.
Minutes = Annotated[int, Field(ge=0)]

#  milliseconds since 1970-01-01 UTC (what JavaScript's Date.now() gives).
TimestampMs = Annotated[int, Field(ge=0)]

# A time of day as "HH:MM" on a 24-hour clock, from "00:00" to "23:59".
Clock = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]

# A day of the week as a number: Sunday is 0, Saturday is 6.
Weekday = Annotated[int, Field(ge=0, le=6)]

# Fixed lists of allowed words. Anything else is rejected.
Energy = Literal["morning", "afternoon", "evening"]  # when the student works best
Freq = Literal["none", "daily", "weekly", "monthly"]  # how often something repeats
TaskType = Literal["assignment", "other"]  # class assignment, or anything else
SchedState = Literal["scheduled", "partial", "unscheduled", "none"]  # result of the fit check
BlockState = Literal["planned", "done", "skipped"]  # what happened to a calendar block


class ApiModel(BaseModel):
    """Base for every model below.

    Sets two rules for all of them:
    - JSON field names are camelCase (needMin), converted from Python's snake_case (need_min).
    - Unknown fields are rejected, so a misspelled field name is an error, not a silent loss.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# =============================================================================
# 2. Preferences
#    How the student likes to work. The fit check uses these for every task.
# =============================================================================


class Prefs(ApiModel):
    """Prefs: the student's general scheduling preferences."""

    # Work hours: the planner only places floating work between these two times.
    work_start: Clock
    work_end: Clock  # "no work after"; at or before work_start means the next day

    # Session lengths, used when a task is split into sessions.
    session_min: Minutes  # preferred session length
    min_session: Minutes  # never shorter than this
    max_session: Minutes  # never longer than this
    break_min: Minutes  # gap kept free after each session

    energy: Energy  # the time of day the student prefers to work
    buffer_days: Annotated[int, Field(ge=0)]  # finish this many days before the deadline


class Override(ApiModel):
    """Override: a temporary relaxation of the preferences.

    Created when a task does not fit and the student chooses to work later or shrink the
    deadline buffer, for one task or for a limited time. A permanent change edits Prefs
    instead, so "always" is not a scope here.
    """

    id: str
    scope: Literal["task", "week", "fortnight"]  # how long the relaxation lasts

    # What is relaxed. None means "not changed, use the normal preference".
    work_end: Clock | None
    buffer_days: Annotated[int, Field(ge=0)] | None

    task_id: str | None  # the task it applies to, when scope is "task"
    until: TimestampMs | None  # when it expires, when scope is "week" or "fortnight"


# =============================================================================
# 3. Repeats
#    See "Repeating tasks" in plan/uiux/user-flows.md.
# =============================================================================


class RepeatEnds(ApiModel):
    """RepeatEnds: when a repeat stops."""

    type: Literal["never", "on", "after"]  # never, on a date, or after N times
    date: TimestampMs | None = None  # used when type is "on"
    count: Annotated[int, Field(ge=1)] | None = None  # used when type is "after"


class RepeatRule(ApiModel):
    """RepeatRule: how often something repeats.

    Examples:
    - Gym on Mon, Wed, and Fri:        freq="weekly", days=[1, 3, 5], mode="all"
    - Laundry on Sat or Sun:           freq="weekly", days=[6, 0], mode="any"
    - The 2nd Tuesday of every month:  freq="monthly", days=[2], nth=2
    """

    freq: Freq
    every: Annotated[int, Field(ge=1)] | None = None  # every N days, weeks, or months
    days: list[Weekday] | None = None  # which weekdays
    mode: Literal["all", "any"] | None = None  # every selected day, or any one of them
    nth: Literal[1, 2, 3, 4, 5, -1] | None = None  # monthly: which one; -1 is the last
    ends: RepeatEnds | None = None


# =============================================================================
# 4. Parts of a task
#    Smaller pieces that live inside a Task.
# =============================================================================


class Milestone(ApiModel):
    """Milestone: one step of an assignment, such as "Outline" or "First draft".

    Milestones let the student report progress, so the remaining time can be re-estimated.
    """

    id: str
    title: str
    est_min: Minutes  # estimated time for this step
    done: bool


class PredictionEntry(ApiModel):
    """PredictionEntry: one time estimate, kept with the inputs it was based on.

    A task collects one of these every time its estimate changes. They are needed later
    to measure how good the estimates were (AGENTS.md: "Model predictions are logged with
    their inputs").
    """

    at: TimestampMs  # when the estimate was made
    minutes: Minutes  # the estimate
    model: str  # which model or method produced it, with its version
    inputs: dict[str, Any]  # what the model knew at the time


class Prediction(ApiModel):
    """Prediction: the first estimate made when the task was added."""

    model: str  # which model or method produced it, with its version
    source: str | None = None  # where the number came from: milestones, the LLM, or the student
    minutes: Minutes
    features: dict[str, Any]  # the facts about the task the estimate used


class Instructions(ApiModel):
    """Instructions: what the student supplied to describe an assignment."""

    kind: str  # "text", "image", "pdf", or "link"
    text: str  # pasted text, when kind is "text"
    file: str  # the file's name, when kind is "image" or "pdf"
    link: str  # the URL, when kind is "link"


class DayWindow(ApiModel):
    """DayWindow: the time of day a floating task may be placed in.

    Example: gym between 17:00 and 21:00. It replaces the student's work hours for that task.
    """

    # Python reserves the word "from", so the field is from_ here and "from" in JSON.
    from_: Clock = Field(alias="from")
    to: Clock


# =============================================================================
# 5. Task
#    Floating work: the to-do list.
# =============================================================================


class Task(ApiModel):
    """Task: one entry on the to-do list, which the planner places in free time.

    A repeating task is stored as one Task per occurrence, all sharing a series_id.
    """

    # --- What it is ---
    id: str
    type: TaskType
    title: str
    course: str  # empty for tasks that are not assignments

    # --- When it can be done ---
    start_after: TimestampMs | None  # earliest start; None means now
    complete_by: TimestampMs | None  # the deadline; None means anytime
    can_split: bool  # may be split into several sessions
    rule: RepeatRule | None  # None means it does not repeat
    series_id: str | None = None  # shared by every occurrence of a repeating task
    day_window: DayWindow | None = None  # the time of day it must fall in, if any
    allowed_days: list[Weekday] | None = None  # the weekdays it may fall on, if limited

    # --- How long it takes ---
    need_min: Minutes  # time still needed
    total_min: Minutes  # time for the whole task, including what is already done
    predicted_min: Minutes  # the estimate, kept for comparing with the actual time
    logged_min: Minutes  # time the student has reported working on it
    pace: Annotated[float, Field(gt=0)]  # 1.0 is on estimate; above 1.0 is slower
    progress_pct: Annotated[float, Field(ge=0, le=100)] | None = None  # when no milestones
    milestones: list[Milestone]  # empty when the student uses none

    # --- Where it stands ---
    status: Literal["active", "complete"]
    sched: SchedState  # whether the fit check could place it
    shortfall_min: Minutes  # minutes the fit check could not place
    created_at: TimestampMs | None = None
    completed_at: TimestampMs | None = None

    # --- How it was estimated ---
    instructions: Instructions | None = None
    prediction: Prediction | None = None  # the first estimate
    prediction_log: list[PredictionEntry] | None = None  # every estimate since

    # --- Sample data marker ---
    sample: bool | None = None  # True for seeded demo data, never for a real record


# =============================================================================
# 6. Block
#    The calendar.
# =============================================================================


class Block(ApiModel):
    """Block: one entry on the calendar.

    Two kinds:
    - "session": time for working on a Task (task_id says which one).
    - "anchored": a plain calendar event or a class.

    The "anchored" flag is separate from the kind. A session the student moved or pinned
    is still kind "session" but has anchored=True, and the planner will not move it.
    """

    # --- What it is ---
    id: str
    kind: Literal["anchored", "session"]
    title: str

    # --- When it is ---
    start: TimestampMs
    end: TimestampMs

    # --- Where it stands ---
    state: BlockState
    anchored: bool  # True means the planner never moves it

    # --- For sessions ---
    task_id: str | None = None  # the task this session works on
    actual_min: Minutes | None = None  # time the student reported, once the session ended

    # --- For events and classes ---
    event_type: Literal["event", "class"] | None = None
    course: str | None = None  # required for a class
    series_id: str | None = None  # shared by every repeat of the same event
    rule: RepeatRule | None = None

    # --- Sample data marker ---
    sample: bool | None = None  # True for seeded demo data, never for a real record


# =============================================================================
# 7. Feedback and history
# =============================================================================


class Pending(ApiModel):
    """Pending: a finished session still waiting for the student's feedback."""

    block_id: str
    ended_at: TimestampMs


class CompletedRecord(ApiModel):
    """CompletedRecord: a finished assignment's predicted and actual time.

    This is a training example: the data the planner learns from. Only finished tasks get
    one. Time logged on a task that was never finished is a lower bound, not an actual
    duration, and must not be stored here (AGENTS.md).
    """

    task_id: str
    title: str
    course: str
    type: TaskType
    predicted_min: Minutes  # what was estimated
    actual_min: Minutes  # what it really took
    at: TimestampMs  # when it was finished
    sample: bool  # True for demo data, which is excluded from any accuracy number


# =============================================================================
# 8. Settings
# =============================================================================


class Notifications(ApiModel):
    """Notifications: which reminders the student has switched on."""

    upcoming: bool  # a session is about to start
    deadlines: bool  # a deadline is close
    changes: bool  # the planner moved something
    weekly: bool  # a weekly summary
    feedback: bool  # a session ended and needs feedback
