# Levra for iOS

The native SwiftUI app. It talks to the JSON API at `/api/v1` (`gymllm/api/`), and
`ios-handoff.md` at the repo root has the full plan. Built so far: the core loop
(Welcome and sign-in, Home, Log, Review, Save), Progress and Day (the Overview,
Sessions and Exercises tabs under a time range, charts, the week calendar and rest
days, search, an exercise's history, and a Day you can step through, edit, delete
and share as a picture), and Friends (profile setup and edit, the feed, high fives
and comments, finding people, requests, invites by pasted link or code, a friend's
profile, Compare, and your own profile on Me). Record, routines and the rest of
Settings come next.

## Build and run

The Xcode project is generated, not committed. After cloning, and after any change
to `project.yml` or adding a file:

    cd ios && xcodegen generate && open Levra.xcodeproj

A Debug build in the simulator talks to `http://localhost:5001`; every other build
talks to `https://levraapp.com`. Start the local server first, from the repo root:

    source .venv/bin/activate
    python ios/scripts/dev_server.py     # or: PORT=5001 python app.py

`dev_server.py` stands in for the model when `.env` has no `SITE_LLM_API_KEY`, so
logging works end to end: whatever you type, it hears a bench press and a run. It
only runs on the local SQLite database and only listens on this Mac.

On Welcome, Debug builds show three seeded accounts (Alex, Sam, Jordan) under the
Google button, and "New": a blank account each time, with no profile and nothing
logged, for profile setup and the empty states.

## Test

With the local server running:

    xcodebuild -project Levra.xcodeproj -scheme Levra \
      -destination 'platform=iOS Simulator,name=iPhone 17' test

`LevraUITests` signs in as Alex and drives the app: `CoreLoopUITests` logs a
workout, edits it on Review, saves, and checks the Day it lands on;
`ProgressUITests` goes through Progress, the calendar, search, an exercise, and a
day's date picker, share picture, editor and delete; `FriendsUITests` gives a high
five, comments, searches People, opens a friend's profile and Compare, edits Alex's
bio, then signs in as somebody new, sets up a profile and joins by Alex's pasted
invite link. Each run adds one workout to Alex in the local database, renames one
of the seeded ones to "Leg day", sets Alex's bio, leaves one new account behind as
Alex's friend, and can leave a rest day behind if it stops halfway. To start clean,
copy `instance/gymllm.db` aside before the first run and put it back afterwards.
Set `TEST_RUNNER_SHOTS_DIR=/some/folder` to keep a screenshot of every screen, and
run `xcrun simctl ui booted appearance dark` first for dark mode.

## Layout

    project.yml       the Xcode project, as text
    Levra/App         entry point, sign-in state, tabs, dates
    Levra/API         the client, the keychain token, models matching gymllm/api/schema.py
    Levra/Theme       colours, fonts, shared components
    Levra/Features    one folder per screen
    Levra/Resources   colour sets, app icon, fonts
    LevraUITests      the core loop, Progress and Day, and Friends, driven in the simulator
    scripts           colors.py (colour sets from static/style.css), dev_server.py

Colours are never written in a view. They are generated from the tokens at the top
of `static/style.css`; after changing one there, from the repo root:

    python ios/scripts/colors.py static/style.css ios/Levra/Resources/Assets.xcassets

## Still to set up by hand

- **Google sign-in:** `GOOGLE_IOS_CLIENT_ID` and `GOOGLE_REVERSED_CLIENT_ID` in
  `project.yml`, from an iOS OAuth client in Google Cloud. Until then the button
  says sign-in isn't set up.
- **Running on a phone:** `DEVELOPMENT_TEAM` in `project.yml`.
