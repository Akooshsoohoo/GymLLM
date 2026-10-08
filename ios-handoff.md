# Levra for iOS: native SwiftUI app (handoff, written 6 Oct 2026)

You are picking this up on a Mac with Xcode. It was planned in a Windows session that could read the code but not build iOS. Nothing below has been implemented. Read this whole file before starting.

## What the owner wants

- A real native iPhone app for Levra, not a web view wrapper. They said "full fledged app".
- Run it on their own iPhone first (free Apple ID, run from Xcode), App Store soon after.
- They are not an iOS developer. Give exact clicks when something has to be done by hand in Xcode, Google Cloud or Render.
- Work on the Mac in a normal git clone. Windows and Mac sync only through git.

## What Levra is today

A Flask + Jinja site, live at https://levraapp.com, deployed on Render (`render.yaml`, `gunicorn wsgi:app`). Users type a workout in plain English, an LLM parses it, they review and save. There is a Progress section and a friends layer (feed, high fives, comments, compare). `README.md` describes every feature; read it.

Two facts shape this job:

- **There is almost no JSON API.** Pages are HTML. Only `/weight-unit`, kudos, `/llm/*` and `/settings/test` return JSON. The app needs a real API.
- **The logic is already separate from the pages.** These modules take and return plain dicts and know nothing about HTML, so the API is mostly thin wrappers:

| Module | What it gives you |
|---|---|
| `gymllm/sessions.py` | `all_rows`, `all_cardio`, `all_weights`, `group_sessions`, `session_numbers`, `next_session`, `exercise_lines`, `session_summary`, `recent_sessions` |
| `gymllm/stats.py` | `week_strip`, `week_streak`, `overview`, `group_rows`, `personal_records`, `exercise_series`, `bodyweight_summary`, `cardio_summary`, `tag_counts`, `top_exercises`, range and period helpers |
| `gymllm/social.py` | profiles, friendships, `visible_data` (the privacy gate), `feed`, `session_cards`, `attach_social`, `toggle_kudos`, `add_comment`, `unseen_count` |
| `gymllm/compare.py` | `compare()` for the side-by-side page |
| `gymllm/parsing.py` | `parse_workout`, `normalize_entry`, `normalize_cardio`, `clean_lift_weight`, `clean_bodyweight`, `clean_duration`, `is_iso_date` |
| `gymllm/quota.py` | `consume`, `refund`, `remaining` for the shared model's daily cap |
| `gymllm/session_meta.py` | per-workout titles, `default_title`, `icon_hint`, `visual` |
| `gymllm/routines.py`, `preferences.py`, `exercises.py` | routines CRUD, weight unit and onboarding flag, exercise matching and tags |

The page handlers that glue these together are `gymllm/routes.py` (1,400 lines) and `gymllm/social_routes.py`. Each API endpoint should mirror one of them; the handler is the spec.

## Rules that are easy to break

1. **Never develop against the real database.** The owner's Windows `.env` points `DATABASE_URL` at production Postgres. On the Mac, write a fresh `.env` with **no** `DATABASE_URL`, so the app uses SQLite in `instance/`. The `/dev` fake-login routes only register when the database is SQLite and the app is not in production (`gymllm/__init__.py`), which is also what you want.
2. **Do not break the website.** It has real users. The existing suite (`tests/`, 14 files) must stay green. Refactors of `routes.py` are fine if the HTML behaviour is unchanged.
3. **Privacy rules live in `social.visible_data`.** Friends see lifts and cardio, never notes, never body weight. Body weight is never shown to anyone else. Any API endpoint returning another user's data must go through `visible_data` / `can_view` / `has_session`, exactly as `social_routes.py` does. Never query another user's rows directly.
4. **Keep Python 3.10 compatible.** `pyproject.toml` sets ruff `target-version = "py310"`. Lint is `ruff check . && ruff format --check .`, line length 100.
5. **Identity is the email address.** There is no User table. Every table keys on `user_email` / `owner_email`. A workout is identified by `(owner_email, date, session)` where `date` is a `YYYY-MM-DD` string and `session` is 0 for the day's first workout. Kudos and comments point at that triple.
6. **"Today" is the user's local date, not the server's.** `routes._client_today()` reads `?today=YYYY-MM-DD` (or a form field, or a `tz_offset` cookie). The iOS client must send `today=` on every request.
7. **Git conventions.** Feature branches named `feat/<thing>`, commits like `feat: ...` / `fix: ...`, merged to `main` with a merge commit titled `Merge feat/<thing>: <one line>`. Work on `feat/ios-app`. Pushing to `main` deploys the site on Render, so do not merge API changes to `main` without the owner saying so.
8. **Weights, distances and durations are stored as text as written** ("185 lbs", "3 miles", "45 min", "40 kg per hand", "bodyweight"). Do not model them as numbers on the client. The server parses them for stats.

## Stage 0: Mac setup

Owner does these (walk them through it):

1. `git clone https://github.com/Akooshsoohoo/GymLLM.git ~/Code/GymLLM`, then `git checkout feat/ios-app`. Not inside Google Drive or iCloud: syncing `.git` and Xcode build output across machines corrupts repos.
2. `brew install xcodegen` (install Homebrew first if missing).
3. Python 3.12: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`.
4. Create `.env` from `.env.example`. Set `FLASK_SECRET_KEY` to a new random value, keep `OAUTHLIB_INSECURE_TRANSPORT=1`, leave `DATABASE_URL` unset. To exercise real parsing locally, set `SITE_LLM_API_KEY` to a Groq key (free at console.groq.com); otherwise parsing has no provider and the log flow redirects to Settings.

You do:

5. Start the server and confirm `/healthz` and `/dev/` work. macOS uses port 5000 for AirPlay Receiver, so the default port may fail to bind; check how `app.py` sets the port and run on 5001 if needed.
6. Run `pytest -q` and the ruff commands to confirm a clean baseline before changing anything.

## Stage 1: JSON API in Flask

New package `gymllm/api/`, one blueprint at `/api/v1`, registered in `gymllm/__init__.py` beside the others.

**Foundation**

- Exempt the blueprint from CSRF (`csrf.exempt(bp)`): it authenticates with bearer tokens, not cookies.
- Give the blueprint its own JSON error handlers. The app-level 404/500 handlers render HTML. Error shape: `{"error": {"code": "quota_exceeded", "message": "..."}}`. Reuse the existing user-facing messages (for example `BAD_LIFT_WEIGHT`, `FUTURE_DATE` in `routes.py`, `LLMError.user_message`).
- Write explicit serialisers (`gymllm/api/schema.py`). Do not `jsonify` the logic modules' dicts blindly: some carry `Profile` objects and datetimes, and explicit serialisers are where rule 3 is enforced.

**Auth**

- `POST /auth/google` with `{"id_token": "..."}` from the Google Sign-In iOS SDK. Verify with `google-auth` (`google.oauth2.id_token.verify_oauth2_token`, audience = a new `GOOGLE_IOS_CLIENT_ID` env var; add `google-auth` to `requirements.txt`, the variable to `.env.example`, `config.py` and `render.yaml`). Require `email_verified`. Return `{"token": ..., "user": ...}`.
- The token: `itsdangerous.URLSafeTimedSerializer(SECRET_KEY, salt="api-token")` over `{email, name, picture}`, max age 30 days (matches `PERMANENT_SESSION_LIFETIME`). Stateless, so no migration. It cannot be revoked one at a time; revisit at Stage 6 for account deletion.
- `POST /auth/dev` with `{"slug": "alex"}`: issues a token for a seeded dev account (`dev_routes.DEV_USERS`, call `dev_routes._ensure_seeded()`). Register it only under the same condition as `dev_routes` (not production, SQLite). This lets the whole app be built before Google Sign-In is configured.
- Extend `auth.current_user_email()` to accept `Authorization: Bearer <token>` before falling back to the cookie session. Every existing helper then works unchanged. `_first_name()` in `gymllm/__init__.py` reads the Google name from the cookie session; give the API its own path using the name inside the token.

**Shared save/parse logic**

`routes.review()` and `routes.confirm()` mix the logic with form parsing and redirects. Pull the core into a module both the HTML routes and the API call (suggested: `gymllm/logflow.py`):

- parse: quota `consume`, call `parse_workout`, `refund` on any failure, `activity.record_parse`. Mirrors `review()`.
- save: validate the date (ISO, not in the future), clean weights and durations, `match_exercise` / `llm_tags` (capped by `MAX_SITE_TAG_CALLS`), `sessions.next_session`, insert `Workout` and `Cardio` rows, `social.set_visibility`, `_save_bodyweight`, `session_meta.set_title`. Mirrors `confirm()`.

`tests/test_routes.py` covers both handlers and must still pass afterwards.

**Model choice in the app:** use the site's shared model only (`LLMConfig.site_default()`). Bring-your-own-key is stored in a browser cookie and local Ollama is called from the browser, so neither carries over. If `SITE_LLM` is not configured, `parse` returns a clear error.

**Endpoints for the core loop** (all need the bearer token; all accept `?today=`)

| Endpoint | Mirrors | Returns / does |
|---|---|---|
| `GET /me` | context processor in `__init__.py` | email, first name, profile (handle, name, avatar, bio, invite URL) or null, weight unit, quota left and limit, unseen social count |
| `GET /home` | `routes.home` | week strip, streak, latest own workout card, recent days, friends' cards (max `HOME_FEED`), getting-started checklist, has_friends |
| `POST /parse` | `routes.review` | body `{text, weight_unit?, routine_name?}`; returns entries, cardio, bodyweight, date, date_from_text, default_title, default visibility, quota left |
| `POST /sessions` | `routes.confirm` | body `{date, title, visibility, entries[], cardio[], bodyweight}`; returns `{date, session}` |
| `GET /day/<when>?session=n` | `routes.day`, `_day_detail` | the day's workouts, stats, kudos and comments, previous/next dates |
| `PUT /preferences` | `routes.weight_unit` | weight unit |

**Tests:** `tests/test_api.py`, following `tests/conftest.py` (in-memory SQLite, `FakeLLM`, `site_app` for quota cases). Cover: bad and expired tokens give 401; dev auth is absent in production config; parse consumes and refunds quota; save round-trips and shows on the HTML day page; a non-friend cannot read a day; notes and body weight never appear in another user's payload.

## Stage 2: the iOS app, core loop

**Project**

- Lives in `ios/` in this repo so the app and API change together.
- Generate the Xcode project from `ios/project.yml` with XcodeGen and commit the YAML, not the `.xcodeproj` (add it to `.gitignore`). This keeps the project editable as text. Put the signing team in `project.yml` (`DEVELOPMENT_TEAM`) once the owner has picked it in Xcode, or regeneration wipes it.
- SwiftUI, iOS 17 minimum (Observation, Swift Charts, `ImageRenderer`, `ShareLink`). No third-party code except Google Sign-In via Swift Package Manager.
- Bundle ID suggestion: `com.levraapp.Levra`. Confirm with the owner; it is hard to change after App Store setup.
- Base URL by build configuration: simulator Debug talks to the Mac's local Flask (`http://localhost:<port>`, with `NSAllowsLocalNetworking` in Info.plist for Debug); everything else talks to `https://levraapp.com`.

**Structure**

```
ios/Levra/
  App/        LevraApp.swift, RootView (signed out vs tabs), AppState
  API/        APIClient (async/await, adds today= and the bearer token, decodes the error shape),
              Keychain token store, Codable models matching api/schema.py
  Theme/      Color tokens, fonts, shared components (pill button, card, stat tile, avatar, value pill)
  Features/   Welcome, Home, Log, Review, Day, Progress, Friends, Profile, Compare, Record, Settings
  Resources/  Assets.xcassets, Fonts/
```

**Design**

- Colours: theme "Fern". The source of truth is the `:root` block and the two dark blocks at the top of `static/style.css` (lines 8 to 110). Copy every token into the asset catalog as a colour set with light and dark values, keeping the names (`bg`, `surface`, `ink`, `you`, `friend`, `primary`, ...). Green (`you`) is the user, clay (`friend`) is other people. Dark mode: primary buttons turn green with dark text. Never hard-code a hex value in a view.
- Fonts: Bricolage Grotesque (headings and numbers) and Instrument Sans (everything else), both open licence on Google Fonts. Bundle the TTFs and list them under `UIAppFonts`.
- Screens, sizes, radii and copy: `design_handoff_mobile_redesign/README.md`, mobile screens 01 to 08. The mockup HTML still shows old coral/blue colours and the name "GymLLM"; the product is called **Levra** and uses Fern. Where the README and the live site disagree, the live site wins (`templates/` and `static/style.css` are newer). Example: the centre tab is now "Record", not "+".
- Copy tone is plain and friendly: "Log it", "Here's what we heard.", "Save workout", "High five", "NEW BEST", "17 free logs left today". Never mention models, providers, API keys or "parse" outside Settings.
- Tabs match `templates/base.html`: Home, Progress, Record (raised centre button), Friends, Me.
- Flat design: only the log card has a shadow.
- Muscle icons: `static/muscle-icons.js` draws them as SVG in the browser and SwiftUI cannot render SVG strings. Use SF Symbols as placeholders in this stage. Later, export the icon set to PDF or SVG assets with a small Node script calling `MuscleIcons.svg(group, ...)`, and have the API return the group from `session_meta.icon_hint`.

**Screens in this stage:** Welcome and sign-in (dev login in Debug, Google otherwise), Home, Log, Review with editable value pills, Save, and a basic Day view to land on after saving.

**Google Sign-In (owner, in Google Cloud Console, same project as the web client):** create an OAuth client ID of type iOS with the bundle ID. It yields a client ID and a reversed-client-ID URL scheme. The client ID goes into the app's Info.plist and into `GOOGLE_IOS_CLIENT_ID` on Render; the URL scheme goes into `CFBundleURLTypes`.

**Running on the owner's iPhone (free Apple ID):** Xcode > Settings > Accounts > add Apple ID. Target > Signing & Capabilities > tick "Automatically manage signing", choose the Personal Team. Plug in the phone, enable Developer Mode on it (Settings > Privacy & Security), trust the developer certificate (Settings > General > VPN & Device Management) on first run. Builds signed this way expire after 7 days and need re-running from Xcode.

**Milestone:** the API is deployed (needs the owner's go-ahead to merge to `main`), the app runs on the owner's phone against levraapp.com, and they log a real workout that also shows on the website.

## Stage 3: Progress and Day

| Endpoint | Mirrors |
|---|---|
| `GET /progress?range=&by=` | `routes.progress` (`stats.overview`, `group_rows`) |
| `GET /sessions?range=&by=` | the Sessions tab of `routes.progress`, `_tile_lines` |
| `GET /exercises`, `GET /exercises/<name>` | `routes.exercises`, `routes.exercise_history` (`stats.exercise_series`) |
| `GET /search?q=` | `routes.search` |
| `PUT /day/<when>/sessions/<n>`, `DELETE ...` | `routes.day_edit`, `_apply_day_edit` (moves titles and reactions when the date changes: `session_meta.move_session`, `move_reactions`) |
| rest rules and overrides | `routes.rest_rule_add`, `rest_rule_delete`, `rest_day_toggle` |

App: Progress with its three tabs and range pills, charts in Swift Charts, the training calendar, Day with previous/next and a date picker, day edit, exercise history, search. Build the share poster as a SwiftUI view rendered with `ImageRenderer` and shared with `ShareLink`; it always uses the light green poster regardless of theme and never includes body weight (the web version is the canvas renderer in `static/app.js`, around line 1339).

## Stage 4: Friends

| Endpoint | Mirrors (`social_routes.py`) |
|---|---|
| `GET/PUT /profile`, `POST /profile/invite-reset` | `profile_edit`, `invite_reset` (handle rules: `social.handle_error`, `suggest_handle`) |
| `GET /u/<handle>`, `GET /u/<handle>/compare?range=` | `profile`, `compare` |
| `GET /friends`, `POST /friends/<action>/<handle>` | `friends`, `friend_action` |
| `GET/POST /invite/<code>` | `invite` |
| `GET /feed` | `feed` (also marks activity seen) |
| `POST /kudos/<handle>/<when>/<n>` | `kudos` (already returns JSON `{count, mine}`) |
| `POST /comments/<handle>/<when>/<n>`, `DELETE /comments/<id>` | `comment`, `comment_delete` |

Most of these sit behind `profile_required`: a user with no profile is sent to profile setup first. Keep that gate in the API (a distinct error code the app turns into the setup screen).

Invite links (`https://levraapp.com/invite/<code>`) should open the app: serve `/.well-known/apple-app-site-association` from Flask and add the Associated Domains capability. That capability needs a paid developer account, so until Stage 6 handle invites by pasting the link or code in the app.

## Stage 5: The rest

- Record: a timer plus named note blocks, sent to parse as one text on Stop. On the web the live recording lives in `localStorage` (`static/app.js`, around line 427). Rebuild natively with on-device persistence so a recording survives the app being killed. Routines pre-fill it.
- Routines CRUD (`routes.routine_*`, `gymllm/routines.py`).
- Settings: units, theme (Light / Dark / System), sign out. Manual entry form (`templates/log_manual.html`).
- Onboarding checklist and dismiss (`preferences.dismiss_onboarding`). Per-day visibility (`social.set_visibility`).

## Stage 6: App Store

- Apple Developer Program, $99 a year. Needed for TestFlight, the store, Associated Domains and Sign in with Apple. Not needed before this stage.
- **Sign in with Apple** is required because the app offers Google sign-in. Apple may hide the user's real email behind a relay address, and Levra identifies people by email, so an Apple login would not match the same person's Google account. This needs a design decision with the owner (simplest: Apple sign-in creates a separate account keyed on the relay address, with a clear note; better: an account-linking table). Do not improvise it.
- In-app account deletion (required by review). Needs a server endpoint deleting every table's rows for that email, and a way to invalidate outstanding tokens.
- Privacy policy URL, privacy nutrition labels, app icon set, screenshots, then TestFlight, then review.

## Things only the owner can do

| When | What |
|---|---|
| Stage 0 | Clone, install tools, create `.env`, get a Groq key if they want local parsing |
| Stage 2 | Create the iOS OAuth client in Google Cloud; set `GOOGLE_IOS_CLIENT_ID` on Render; approve merging the API to `main`; sign in to Xcode and pick the team; set up the phone |
| Stage 6 | Join the Apple Developer Program; decide the Sign in with Apple linking question; write or approve the privacy policy |

## How to verify each stage

- Server: `pytest -q`, `ruff check . && ruff format --check .`.
- App: `xcodegen generate` in `ios/`, then `xcodebuild -scheme Levra -destination 'platform=iOS Simulator,name=<an installed iPhone>' build`. Boot the simulator, install and launch with `xcrun simctl`, and take `xcrun simctl io booted screenshot` of each new screen in light and dark. Compare against the live site at phone width and the design handoff.
- Run against the local Flask with the dev accounts (`alex`, `sam`, `jordan`: seeded with eight weeks of data and already friends, so feed, kudos and compare have content). For empty states, sign in as a brand-new email; the dev accounts are no use for that.
- From the Stage 2 milestone on: the owner logs a real workout on the phone and checks it on the website.

## Open questions to raise with the owner, not to guess

1. Bundle ID and the app's display name (assumed `com.levraapp.Levra`, "Levra").
2. When the API may be merged to `main` and deployed.
3. Sign in with Apple account linking (Stage 6).
4. Whether bring-your-own-key should exist in the app at all.
