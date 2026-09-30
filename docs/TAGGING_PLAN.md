# Plan: maximal exercise tagging (every exercise, every variation)

## Where we are today

- `data/taggedExerciseList.csv`: 235 rows, `exercise,tags`, tags joined with `;`, 3–7 per row, 39 distinct tags.
- Tags are **coarse and copy-pasted per family**: every row variant, every bench angle and every curl grip carries the same tags, so a tag can't tell `incline barbell bench press` from `decline barbell bench press`, or `wide-grip lat pulldown` from `reverse-grip lat pulldown`.
- Only muscle and movement-pattern tags exist. Equipment is nearly absent (`dumbbell` appears twice), and there are no angle, grip, stance, or position tags.
- The vocabulary is ad hoc: `back` / `upper back` / `lats` / `traps` overlap, `legs` is redundant with `quads` / `hamstrings`, and `abs` is next to `core`.
- The list has **duplicate and near-duplicate rows**, for example `barbell shrug` ×2, `cable rear delt fly` ×2, `reverse hyperextension` ×2, `arnold press` ×2, `standing calf raise (machine)` ×2, plus naming-style drift such as `(barbell)` suffix versus `barbell` prefix.
- Tags are **snapshotted into each `Workout` row at log time** (`routes.py` ~L743–762). Tags improved in the CSV do not reach history unless we re-tag it. `routes.py` ~L931 already shows a re-tag path on edit.
- **Consumers treat every non-`MOVEMENT_TAGS` tag as a muscle.** `stats.tag_counts`, `compare.muscle_split`, `session_meta.icon_hint` and `MuscleIcons.forTags` all do this. Adding equipment, angle or grip tags naively would put "barbell" in the muscle chart and break the day icon. The taxonomy work has to solve this first.
- Unknown exercises are tagged by the LLM with a hardcoded, short tag list (`TAG_SYSTEM`). Its output needs to match the new vocabulary.

## Goal

Every exercise in the list, and every sub-variation that can reasonably be logged, gets a complete, consistent tag set across every dimension below. Tags are generated from structured attributes, not hand-typed, so they can't drift.

## Step 1: Define the taxonomy (one source of truth)

Add `data/tagTaxonomy.csv` (or a `gymllm/taxonomy.py` constant) listing every allowed tag, its **category**, and optional **aliases** and **implies**. Categories:

| Category | Examples | Counts as "muscle" in charts? |
|---|---|---|
| `primary_muscle` | chest, lats, quads, hamstrings, glutes, biceps, triceps, side delt, calves, abs | yes |
| `secondary_muscle` | front delt, rear delt, traps, forearms, brachialis, adductors, lower back, obliques | yes, but see Step 5 |
| `muscle_region` | upper chest, lower chest, long head, lateral head, medial head, inner quad, outer quad, upper back, mid back | no (drill-down only) |
| `muscle_group` | chest, back, shoulders, arms, legs, core (coarse rollup, derived) | yes, this is what icons use |
| `movement_pattern` | horizontal push, vertical push, horizontal pull, vertical pull, squat, hinge, lunge, carry, rotation, anti-rotation, flexion, extension, abduction, adduction, plantarflexion, dorsiflexion | no |
| `push_pull_legs` | push, pull, legs | no |
| `body_split` | upper, lower, full body | no |
| `mechanics` | compound, isolation, unilateral, bilateral, alternating | no |
| `equipment` | barbell, dumbbell, cable, machine, smith machine, ez bar, trap bar, safety bar, cambered bar, landmine, kettlebell, band, bodyweight, weighted, assisted, plate, sandbag, medicine ball, stability ball, sled, rope, v-bar, straight bar | no |
| `angle` | flat, incline, decline, low, mid, high, overhead, seated, standing, lying, prone, supine, kneeling, half-kneeling, chest-supported, bent-over | no |
| `grip` | wide grip, close grip, neutral grip, supinated, pronated, reverse grip, mixed grip, hook grip, snatch grip, underhand, overhand | no |
| `stance` | narrow stance, wide stance, sumo, staggered, split stance, single leg, high bar, low bar, front-loaded, goblet | no |
| `tempo_and_range` | deficit, pause, dead stop, pin, board, partial, full range, eccentric, isometric, explosive | no |
| `attribute` | grip demand, stabilization, balance, power, core bracing, hypertrophy, strength, rehab, bodyweight-friendly | no |
| `difficulty` | beginner, intermediate, advanced | no |
| `load_type` | free weight, machine-guided, cable, bodyweight, loaded carry | no |
| `joint_stress` | shoulder-friendly, knee-friendly, back-friendly, high spinal load | no |
| `family` | bench press, overhead press, row, pulldown, pull-up, squat, deadlift, lunge, curl, extension, raise, fly, shrug, calf raise, carry, hip thrust... | no, used for grouping variants |

Rules for the registry:

- **Every tag in the CSV must exist in the registry.** A test enforces it.
- `aliases` collapse synonyms on write (`abs` → `core`, `lat` → `lats`, `delts` → the specific delt, `tris` → `triceps`). Use singular/plural and spelling as one canonical form.
- `implies` gives free derived tags, for example `incline` → `upper chest`; `sumo` → `adductors` + `wide stance`; `hamstrings` → `lower` and `legs`; `chest` → `upper` and `push` where true.
- Retire `legs` as a hand-typed tag and derive it (`quads`, `hamstrings`, `glutes`, `calves`, `adductors` → `legs`).

## Step 2: Model exercises as structured records, then generate tags

Add `data/exerciseAttributes.csv` (one row per exercise) with columns, not free text:

`exercise, family, equipment, angle, grip, stance, primary_muscles, secondary_muscles, regions, pattern, mechanics, unilateral, difficulty, notes`

A build script (`scripts/build_tags.py`) expands attributes plus registry `implies` into the final `;` list and writes `data/taggedExerciseList.csv`. The runtime format does not change, so `exercises.py` and existing tests keep working. Benefits: a variant is one row that differs in one attribute, and hand edits can't make `incline` rows lose `upper chest`.

## Step 3: Enumerate every variation (the "max out" part)

1. **Clean the current 235 first.** Merge duplicates and choose one naming convention (recommend `<equipment> <variation> <movement>` with no parenthetical suffix, for example `dumbbell romanian deadlift`). Keep old spellings as `alias` rows so existing logs still match.
2. **Generate the variation grid per family** and keep every combination that is realistic. For each family, cross the applicable dimensions:
   - **Presses** (bench, overhead, floor, spoto, board, pin, z, log): equipment (barbell, dumbbell, smith, machine, cable, landmine) × angle (flat, incline 15/30/45, decline) × grip (standard, close, wide, reverse, neutral) × pause or partial variants × unilateral (single-arm).
   - **Rows**: equipment × torso angle (bent-over, chest-supported, seal, inverted, Pendlay, Meadows, t-bar, landmine, dead stop, high, low) × grip (overhand, underhand, neutral, wide, close) × unilateral.
   - **Vertical pulls**: pulldown and pull-up/chin-up × grip (wide, close, neutral, reverse, mixed) × equipment (cable, machine, bodyweight, weighted, assisted, band) × single-arm × behind-the-neck.
   - **Squats**: barbell (high bar, low bar, front, safety bar, cambered, box, pause, zercher, Jefferson), machine (hack, V, pendulum, belt), dumbbell/kettlebell (goblet, sumo), Smith, split-stance family (Bulgarian, lunge forward/reverse/walking/lateral/curtsy, step-up) × equipment.
   - **Hinges**: conventional, sumo, trap bar, deficit, snatch grip, rack pull, Romanian, stiff-leg, single-leg RDL, good morning, axle × equipment; hip thrust and glute bridge × equipment × single-leg; back extension and reverse hyper × angle.
   - **Isolation upper**: curls (barbell, EZ, dumbbell, cable, preacher, incline, spider, concentration, hammer, Zottman, drag, reverse, bayesian) × grip; triceps (pushdown rope/bar/v-bar/single-arm, skullcrusher, overhead extension, kickback, JM press, dips) × equipment × single-arm; raises (lateral, front, rear delt, upright row) × equipment × single-arm.
   - **Isolation lower**: leg extension and curl (seated, lying, standing, single-leg, Nordic), calf raises (standing, seated, donkey, leg-press, single-leg, tibialis), hip abduction and adduction × equipment × position.
   - **Core, carries, rotation, conditioning-strength**: crunch, sit-up, leg raise (hanging, lying, captain's chair), ab wheel and rollout, planks (weighted, side, RKC), Pallof, woodchop (high-low, low-high), landmine twist, side bend, farmer/suitcase/zercher/overhead/yoke/sandbag carries, Turkish get-up, Olympic lifts and variants (clean, snatch, jerk, hang, power, from blocks), kettlebell swing, sled push/pull.
   - **Bodyweight and calisthenics**: push-up variants (incline, decline, diamond, archer, pike, deficit, weighted), inverted row, muscle-up, handstand push-up, dips, L-sit, pistol squat.
   - **Neck, forearm, grip**: wrist curl and extension, reverse wrist curl, farmer hold, dead hang, plate pinch, neck work.
3. **Write each variation as its own row** with its attributes filled in, and mark which attributes changed from its parent (`parent` column) so the UI can group "variations of X".
4. **Every row must be fully tagged**: at least one of each mandatory category (`primary_muscle`, `movement_pattern`, `mechanics`, `equipment`, `body_split`). Optional categories are filled when they apply. A validation test fails on any row missing a mandatory category.

Target size: roughly 235 today → 600–900 rows after the grid is pruned for realism. Each row carries about 12–20 tags instead of 3–7.

## Step 4: Keep matching working as the list grows

`match_exercise` is fuzzy and token-based, so more near-identical names raise the chance of a wrong match, for example `incline bench` landing on the wrong variant.

- Add an `aliases` column (for example `bench`, `db bench`, `lat pull`, `rdl`, `ohp`, `skullies`) and match aliases before the fuzzy step.
- Make the token-subset rules **attribute-aware**: parse the raw text for known equipment, angle and grip words, then pick the exercise whose attributes match the most of them.
- Keep the generic-name default (`bench press` → `barbell bench press`), now explicit through a `default_for_family` flag instead of "fewest extra words."
- Raise the test bar: every canonical name matches itself exactly, every alias resolves to exactly one exercise, and a corpus of about 100 realistic raw strings resolves to the expected variant.

## Step 5: Stop new tags from corrupting the existing features

- Replace the hardcoded `MOVEMENT_TAGS` in `stats.py` with a registry lookup, so **only muscle-category tags feed `tag_counts`, `compare.muscle_split` and `icon_hint`**.
- Decide how secondary muscles count. Recommended: count a primary at weight 1 and a secondary at 0.5 in the muscle chart, which also fixes today's over-crediting of triceps and front delts on every press. This is optional and can ship separately, and the flat behavior stays the default until then.
- Extend `muscle-icons.js` `forTags` to use the derived `muscle_group` tags (chest, back, shoulders, arms, legs, core), so equipment and angle tags can never influence the day icon.
- `routes.py` ~L806 joins tags into the search text. With far more tags, add equipment, angle and grip terms there on purpose so "incline dumbbell" searches work, but keep the ranking unchanged for exact exercise names.

## Step 6: Update the LLM fallback to the same vocabulary

- Build `TAG_SYSTEM` from the registry at import, listing allowed tags **by category** and asking for one answer per category, for example `{"equipment": [...], "primary_muscles": [...], "angle": [...], ...}`.
- Validate and normalise the reply with the registry (`clean_tags` → drop unknown tags, resolve aliases, add `implies`). Anything unknown is dropped, or logged for review, instead of being stored.
- The browser-side path (`static/app.js` ~L285–306) reads the prompt from `/llm/tag-targets`, so it picks up the new prompt automatically. Its parse step needs the same per-category to flat-list conversion, and the server must re-validate what the browser posts (`routes.py` ~L746 currently trusts it).

## Step 7: Backfill history

Stored `Workout.tags` and `Routine` entries predate the new tags.

- Add a one-off migration command (`flask retag`) that re-runs `match_exercise` over each distinct exercise name in `Workout` and rewrites `tags` (and canonical `exercise` only when an alias maps to a renamed exercise). Run it in batches by distinct name, not per row.
- Make it idempotent and dry-run by default (prints a diff of old → new tags per exercise and the number of rows affected). Leave LLM-tagged, unmatched exercises alone, or re-tag them through the new validated path.
- Keep `README` and `.env.example` notes on running it on Render (`render.yaml`).

## Step 8: Expose the tags in the product

- `exercise.html` / `exercises.html`: show tags grouped by category as chips, and filter the exercise list by any combination (for example equipment = dumbbell AND angle = incline).
- Variation navigation: on an exercise page, list "other variations of this family" using `family` and `parent`, and let progress/compare charts roll up to the family.
- Progress and compare: add a "by equipment", "by movement pattern" and "by family" breakdown next to the current muscle split, since these now exist.

## Step 9: Tests and guardrails

- `test_taxonomy.py`: no unknown tags in the CSV, no duplicates within a row, all aliases resolve, every `implies` target exists, no cycles.
- `test_exercises.py`: no duplicate exercise names (after normalisation) or alias collisions; every row has all mandatory categories; counts of tags per row within the expected range.
- Consistency checks that catch the drift we have today: the same `family` + same attributes ⇒ the same derived tags; `incline` ⇒ `upper chest`; `unilateral` rows carry `unilateral`; `dumbbell` in the name ⇒ `dumbbell` tag (and likewise for barbell, cable, machine and smith machine).
- Regression tests for `stats.tag_counts`, `compare.muscle_split` and `icon_hint` confirming equipment, angle and grip tags never show up as muscles.
- Generator test: `scripts/build_tags.py` output equals the committed `taggedExerciseList.csv` (CI fails if someone edits the output by hand).

## Suggested order of delivery

1. Taxonomy registry + Step 5 decoupling (charts and icons safe) + consistency tests. No data change yet.
2. Attribute file for the existing 235 (cleaned and de-duplicated) + generator; output replaces the CSV. Matching still passes.
3. Variation grid expansion family by family (Step 3), each family one PR with its tests.
4. Alias/attribute-aware matching (Step 4).
5. LLM vocabulary and validation (Step 6).
6. Backfill command (Step 7), run once in production.
7. UI surfacing (Step 8).

## Decisions worth confirming before starting

- Naming convention for exercises (prefix style versus the current `(equipment)` suffix), since it affects matching and the backfill.
- Whether secondary muscles should be weighted in the muscle chart, or only tagged.
- Upper bound on the variation grid. "Every combination" is thousands of rows, so the plan prunes to combinations a lifter could plausibly perform. If you want literally every combination, say so and the generator can emit the full grid, at the cost of a much noisier picker and match step.
