# Active work

Status: Active

Purpose: record current work, unresolved decisions, and the next authorized step.
Repository organization and development rules live in the [README](../README.md).

## Confirmed state

- Project direction: adaptive student planner; team and adviser confirmed.
- Product scope, stack, architecture, and first-feature acceptance criteria remain
  undecided. No provisioned services exist. On `hxu/ui-first-pass`, a first-draft web
  app in [web/](../web/README.md) uses React and TypeScript; that frontend choice is
  [proposed](../docs/decisions/0001-frontend-react-typescript.md) and is settled with the
  pull request. The backend and the rest of the stack are undecided (see below).
- Allen owns repository organization and operating rules. The current Git policy
  allows direct commits to `main`; branches, PRs, branch protection, and templates
  are intentionally not required.
- `team/meetings/` holds student-written meeting summaries (`meeting_1.md` so far).
  AI reads `team/` and may edit all of `docs/`, but humans make the decisions.
- The organization commit went to `main` (authorized by Allen). Howard's UI work is on
  `hxu/ui-first-pass`; its commits are drafts for team review.

## Earlier work

The planning cleanup authorized by Allen is complete; its record is in
[archive/2026-10-planning-cleanup.md](archive/2026-10-planning-cleanup.md). Still open from
it:

- Student-written meeting summaries in `team/meetings/` (the first, `meeting_1.md`, exists).
- The overview still contains explicitly unratified scope and success criteria. Agent
  conventions in AGENTS.md still carry conditional assumptions about the backend
  (FastAPI, Supabase, a worker); those are not a stack decision.

## UI first pass (proposed, branch `hxu/ui-first-pass`)

Status: Proposed, waiting for a PR and team review. Not adopted by the team. The dated history of this branch
is in [ui-first-pass-changelog.md](uiux/ui-first-pass-changelog.md); the current state is in
the handoff below.

## Handoff: UI first pass (as of 2026-10-04)

**Where things stand.** Committed on `hxu/ui-first-pass`: the goal and first MVP flows
(`bffc8d4`), then the plain-JS prototype and its docs (`8155c87`). **Uncommitted** in the
working tree since then: the conversion of the prototype to React and TypeScript, and the
flowchart validation.

- New: `web/` (the app, its README and DESIGN.md, `package.json` and `package-lock.json`),
  `plan/uiux/flow-validation.md`, `docs/decisions/0001-frontend-react-typescript.md`.
- Deleted: the plain-JS code under `prototype/` (`index.html`, `styles.css`, `js/`,
  `test/`); its README and DESIGN.md moved to `web/`.
- Modified: `plan/uiux/ui-ux.md`, `plan/uiux/user-flows.md`,
  `plan/uiux/ui-first-pass-changelog.md`, and this file. For consistency with the branch:
  `README.md`, `AGENTS.md`, `scripts/check.sh`, `scripts/test.sh`, `plan/testing.md`,
  `plan/questions.md`, `docs/decisions/README.md`. Allen owns the README and the
  operating rules in AGENTS.md; those edits describe this branch and are his to review in
  the PR.
- Moved: the completed planning-cleanup log, from this file to
  `plan/archive/2026-10-planning-cleanup.md`.
- Not from the AI sessions, left untouched: `prototype/brand/` (never committed).

**Read first:** [uiux/ui-ux.md](uiux/ui-ux.md) maps every UI/UX file and its single job.
[uiux/user-flows.md](uiux/user-flows.md) holds the rules that decide when work is
scheduled (two master flowcharts are the source of truth; the smaller charts under them are
derived). [web/DESIGN.md](../web/DESIGN.md) holds the supporting UI rules and explains how
the app implements both. [uiux/flow-validation.md](uiux/flow-validation.md) shows, node by
node, that the app follows both charts. [ui-first-pass-changelog.md](uiux/ui-first-pass-changelog.md)
records what changed and when.

**Vocabulary now in use:** tasks are **anchored** (given a time) or **floating**;
floating tasks are a **class assignment** or **not an assignment**. The scheduler's core is
the **fit check** (also called fill logic).

**How to verify:**

- `./scripts/check.sh` from the repository root: lint, typecheck, 74 tests (31 engine,
  40 flowchart, 3 Weekly Plan), and a production build. All passing as of this handoff
  (2026-10-04). Needs `npm install` in `web/` first, and Node 22.22 or newer.
- `./scripts/test.sh` runs every suite, or a path (`web/src/domain`) or a name filter
  (`-t "fit check"`).
- `cd web && npm run dev`, then follow the walkthrough in [web/README.md](../web/README.md).
- The Chrome scripts used for browser checks (screenshots, the side-by-side walkthrough of
  the old and new versions, drag checks, the "no arrow through a box" chart check) were
  throwaway and are not in the repo. DESIGN.md section 13 describes them.

**Open, for the team or the next session:**

- Howard commits the conversion, then opens a PR from `hxu/ui-first-pass` to `main` (the
  Git policy does not require PRs, so this is a review choice).
- Team review: the app, user-flows.md (its "Still open" list and the defaults chosen while
  building the prototype), [decision 0001](../docs/decisions/0001-frontend-react-typescript.md)
  (React and TypeScript, first draft not throwaway), and the observation in
  [flow-validation.md](uiux/flow-validation.md#observations-for-the-team).
- Placeholders to refine: re-estimation math, preference defaults (question 8), placement
  strategy and re-placing moved work (question 9), per-task scheduling inputs
  (question 10), the LLM.
  Prototype limits to remove later: 28-day "anytime", 8-week never-ending repeats.
- Allen reviews the README and AGENTS.md changes in the PR (run instructions, status,
  stack rows, "Where things live", verification, setup commands).
- Not decided: the backend and the rest of the stack, how duration is predicted.
- Then, as before: work through [questions.md](questions.md), starting with the first
  version's scope, MVP acceptance criteria, and the stack. Record explicit human choices
  before implementation.

## Backend and saving (proposed, branch `feat/backend-fastapi`)

Status: Proposed by Sheila Bukenya, built with AI assistance. Not reviewed or adopted by the
team. The backend stack is still an open decision ([question 4](questions.md)); this branch
is a candidate to review, and no decision record has been written for it yet.

**What exists (as of 2026-11-19).** Committed: the FastAPI skeleton and the Pydantic models
(`b33065d`). **Uncommitted** in the working tree: every endpoint and the web app's
connection to them.

- [backend/](../backend/README.md): FastAPI, with models mirroring `web/src/domain/types.ts`.
  Endpoints for tasks, calendar blocks, and preferences, plus `GET /sync` (read everything)
  and `POST /sync` (save many changes, all or none, safe to retry). Data is kept in memory:
  no database, no accounts.
- `web/`: new `src/state/api.ts`, `src/state/sync.ts`, `src/components/SyncStatus.tsx`, and
  `.env.example`; small edits to `src/main.tsx`, `src/App.tsx`, `src/styles.css`, and
  `vite.config.ts`. Saving to the backend is off unless `VITE_SYNC=on`; with it off the app
  behaves as before. `src/state/store.ts` and the scheduling engine are unchanged. How to run
  it is in [web/README.md](../web/README.md#save-to-the-backend-optional-proposed).

**How to verify.** `./scripts/check.sh` runs both halves: 100 web tests and 90 backend tests,
all passing on 2026-11-19. Needs `uv` for the backend. The sync code was also run against a
live backend, including restarts, with a throwaway script that is not in the repo. Nobody has
clicked through it in a browser yet.

**Open, for the team or the next session:**

- Howard has not been told about the edits in `web/`. He should review them.
- Team decisions this depends on: the backend stack and database (question 4), and whether
  the server or the web app owns the default preferences (question 8; today the web app does,
  and `GET /prefs` answers 404 until some are saved).
- Not built: a database, accounts and per-student ownership, and server storage for
  finished-assignment records (`completed`, the data the adaptive part learns from), pending
  feedback, temporary relaxations, and notification settings.
- Clock times ("09:00") are in the student's timezone, which is not stored anywhere yet.
- The root README still says there is no backend. Allen owns it; update it with the PR.
- `syllabus-testset/` is untracked and belongs to the separate `feat/course-doc-import` work.

## Next step

Howard reviews and commits the React conversion on `hxu/ui-first-pass`, then opens a PR to
`main`. The team then reviews the app, [uiux/user-flows.md](uiux/user-flows.md), and
decision 0001, and decides what merges. The repository-organization commit referenced
earlier in this file is already on `main`.
