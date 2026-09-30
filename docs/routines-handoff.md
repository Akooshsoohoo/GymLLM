# Routines: handoff

## Goal

Add **Routines** next to the existing record flow. A routine is a named template made of
named blocks. Starting a workout from a routine pre-fills the recorder with those blocks;
the user fills in reps/weights as they train, edits freely, and Stop sends it through the
same LLM parse → review → confirm path as today. Nothing about parsing or saving changes.

## Product spec

**Record screen (`/record`, idle state)**
- Keep the big "Start workout" button (empty workout, as today).
- Add a **Routines** entry beneath it (a list of the user's routines, each tappable to
  start, plus a "Manage routines" link to `/routines`). Empty state: "No routines yet. Create one."
- Starting from a routine goes straight to the live state, timer running, blocks pre-filled.

**Routines screen (`/routines`)**
- List of routines (name, block count). Actions: New, Edit, Duplicate, Delete (confirm).
- **Editor** (`/routines/new`, `/routines/<id>/edit`):
  - Routine name (required, max 60 chars).
  - Any number of blocks; add / remove / reorder (up/down buttons are enough, no drag needed).
  - Each block: a **name** (optional, max 40, e.g. "Chest", "Warm-up") and a free-text
    **body**, same textarea as the recorder, e.g.
    ```
    Bench press 185 lbs, 3 sets of ___
    Incline dumbbell press 60 lbs, 3 sets of ___
    ```
  - `___` is the "fill me in" placeholder (see Recorder behaviour).

**Recorder (live state)**
- Blocks come from the routine (name + body). User edits anything, adds/removes blocks.
- Block name becomes an editable input in the block head (replacing the fixed "Block N"
  label). This applies to ad-hoc workouts too; empty name falls back to "Block N" as a
  placeholder, so nothing changes for people who ignore it.
- Routine name is remembered for the session title (below).

**Green outline (both views)**
- The block containing the focused text field (body *or* name input) gets a green outline
  using `--you`. Implement with `:focus-within`, no JS.
- Recorder already does a 1.5px `--you` box-shadow on `.rec-block:focus-within`
  (`static/style.css:1124`). Extract a shared `.block` style/class used by both the
  recorder block and the routine-editor block so they cannot drift. Make it a clearly
  visible 2px outline in both light and dark themes (`--you` is defined for both), keep
  the border-radius, and don't add a second focus ring on the inner field
  (`.rec-text:focus` already has none).

## Data model (`gymllm/models.py`)

New tables; `db.create_all()` creates them on start, no migration (see the docstring at the
top of models.py). Do not touch the existing `Workout`/`Cardio` tables.

```python
class Routine(db.Model):
    __tablename__ = "routine"
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String, nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

class RoutineBlock(db.Model):
    __tablename__ = "routine_block"
    id = db.Column(db.Integer, primary_key=True)
    routine_id = db.Column(db.Integer, db.ForeignKey("routine.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(40), nullable=True)
    body = db.Column(db.Text, nullable=False, default="")
```

Server-side (not localStorage) so routines follow the user across devices. Add a small
`gymllm/routines.py` module for queries/validation (mirrors `session_meta.py` /
`sessions.py`); routes stay thin. Every query is scoped by `user_email`; a routine that
isn't the caller's is a 404.

## Routes (`gymllm/routes.py`, all `@login_required`, POSTs CSRF-protected like the rest)

| Route | Purpose |
|---|---|
| `GET /routines` | list |
| `GET/POST /routines/new` | create |
| `GET/POST /routines/<int:id>/edit` | edit (replace blocks wholesale on save) |
| `POST /routines/<int:id>/delete` | delete |
| `POST /routines/<int:id>/duplicate` | copy as "<name> (copy)" |
| `GET /record?routine=<id>` | `record()` passes that routine's blocks to the template |

`record()` also passes the user's routine list for the idle screen. Editor form: repeated
`block_name` / `block_body` fields in order; cap at ~20 blocks and ~4000 chars per body.

## Recorder changes (`templates/record.html`, `static/app.js` ~L454–570)

- Recording state in `recStore` today is `{startedAt, blocks: [text]}`. Change to
  `{startedAt, routine: {id, name} | null, blocks: [{name, text}]}`. **Read old-shape
  state defensively** (`typeof b === "string"` → `{name: "", text: b}`), because people
  can have a recording in localStorage across the deploy.
- Server passes the routine's blocks as JSON in a `data-` attribute on `[data-recorder]`;
  clicking a routine on the idle screen navigates to `/record?routine=<id>` and the page
  calls `goLive` with those blocks and `startedAt: Date.now()`. If a recording is already
  live, don't overwrite it: show the live one (existing behaviour) and ignore the param.
- Block template gets a name `<input>` in `.rec-block-head`. `save()` persists names too.
  Note `.rec-block-head` is currently hidden unless there are 2+ blocks
  (`.rec-blocks.has-many`); it must now always show when a block has a name.
- **What gets parsed:** `joined()` currently joins block bodies with a blank line. Emit each
  named block as `Name\nbody`; unnamed blocks as just `body`. No parser/prompt change
  needed for v1; the name is a plain header line the model reads as context.
- **Unfilled placeholders:** before building the text, drop any line still containing `___`
  (an exercise the user skipped) and show the count in the finish sheet
  ("2 lines left blank, skipped"). Blocks that become empty are omitted. Keep the
  existing `data-rec-log` disabled-when-empty logic based on the result.
- **Session title:** if started from a routine, post `routine_name` as a hidden field on
  `#rec-form` → `/review` (carry through `review.html` context) → `/confirm`, which calls
  `session_meta.set_title(user_email, when, routine_name)` when the field is present and
  non-empty. (`set_title` already ignores the default title and lets a later rename win.)

## Tests (`tests/test_routes.py`; add `tests/test_routines.py` for the module)

- CRUD happy path; another user's routine → 404 on view/edit/delete/duplicate; CSRF/login required.
- Validation: empty routine name rejected; over-length name/body truncated or rejected
  (pick one, be consistent); block order preserved; edit replaces blocks.
- `/record?routine=<id>` renders the blocks; unknown/foreign id → 404 (or falls back to
  idle, your call, but test it).
- Confirm with `routine_name` sets the day's title; without it, unchanged.
- JS behaviour (placeholder stripping, old-state migration, joined text) has no test
  harness in the repo; verify manually in the browser and note what you checked.

## Acceptance criteria

1. Can create a routine with a name and several named blocks, edit, reorder, duplicate, delete.
2. Record screen shows Start workout plus the routines list; tapping a routine starts a
   timed workout with those blocks filled in.
3. Reload / lock the phone mid-workout: blocks, names and routine come back.
4. Focusing any field inside a block (in the recorder and the routine editor) shows a green
   outline on that whole block, in light and dark themes, on mobile width.
5. Finishing a routine workout parses and saves through the existing review/confirm flow;
   the day's title is the routine name.
6. Ad-hoc "Start workout" behaves as before for anyone who never touches routines.

## Out of scope for v1

Structured per-set fields (the body stays free text on purpose, it's what the parser
consumes), sharing/publishing routines to friends, "last time you did this" prefill,
routine history/stats, drag-and-drop reordering.

## Assumptions to check with the owner

- "Routines screen" is reached from the record screen and is a separate page, not a tab.
- Block name goes to the parser as a header line; if the model misreads names as exercises,
  add one line to `SYSTEM_PROMPT` in `gymllm/parsing.py` saying a lone short line is a
  section heading, not an exercise.
