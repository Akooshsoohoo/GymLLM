# Handoff: GymLLM mobile redesign (direction 1)

## Overview
A mobile-first visual and copy redesign of GymLLM (repo `Akooshsoohoo/GymLLM`). The goal is to make it feel like a warm, general-audience **social gym log** instead of a developer tool. Features and data don't change. What changes is the look, the wording, how things are ranked on each screen, and the navigation.

## About the design files
`GymLLM Mobile Redesign.dc.html` is a **design reference built in HTML**. It's a static mockup of eight phone screens, not production code. Open it in a browser; `support.js` must sit next to it.

Recreate these screens in the existing codebase: Flask + Jinja templates in `templates/`, a single `static/style.css`, and `static/app.js`.
- Use CSS classes in `style.css`, not inline styles.
- Keep all existing routes, forms, CSRF fields, hidden inputs and `data-*` hooks that `app.js` relies on.

## Fidelity
**High-fidelity** for colour, type, radii, spacing and copy. Layout is designed at a 390px-wide viewport and should reflow: use fluid widths and a max content width of about 560px on larger screens. Charts are simplified in the mock. Keep the existing SVG chart renderer in `app.js` and restyle it with the new tokens.

## Global changes
- **Theme:** Fern light plus Fern dark (see Design tokens and `theme.css`).
- **Fonts:** drop Inter. Load Google Fonts `Bricolage Grotesque` (500–800, opsz 12..96) for headings and numbers, and `Instrument Sans` (400–700) for everything else.
- **Navigation:** replace the top nav with a fixed **bottom tab bar** on mobile.
  - Tabs: Home · Progress · **+** (Log, raised centre button) · Friends · Me.
  - Height 88px, white, 1px top border `#E7E0D5`.
  - Labels 12px/600, `#8A8175`; the active tab uses ink `#1C1915` with a filled icon.
  - The centre button is 58px, ink background with a cream `+` and a 4px cream border, raised 28px above the bar.
  - Settings moves under **Me**.
- **Copy tone:** friendly and plain. Don't mention models, providers, API keys or "parse" in the main flows. That stays on the Settings page.
  - "Parse workout" → "Log it"
  - "Review and confirm" → "Here's what we heard."
  - "Save to log" → "Save workout"
  - "Kudos" → "High five"
  - "PR" → "NEW BEST"
  - Quota text becomes "17 free logs left today"
- **Home:** today `main.home` is the log form plus a friends aside. Split it into a Home feed (screen 04) and a Log screen (screen 02, opened from the + tab).

## Design tokens
**Colours: theme "Fern" (6a light / 6b dark in `GymLLM Theme Explorations.dc.html`)**
All colour values live in `theme.css` in this folder. Paste it at the top of `static/style.css` and use only its variables; never hard-code hex values.
- The mockups in `GymLLM Mobile Redesign.dc.html` still show the earlier coral/blue colours. **Map them as follows:**
  - coral → `--you` (green)
  - coral tint and dark → `--you-tint`, `--you-ink`
  - blue → `--friend` (clay)
  - blue tint and dark → `--friend-tint`, `--friend-ink`
  - ink buttons → `--primary`
- **Dark mode** follows `prefers-color-scheme`. Add a Light / Dark / System control in Settings that sets `data-theme` on `<html>`, saved in localStorage and applied by an inline script in `<head>` before first paint.
- In `base.html`, use `<meta name="color-scheme" content="light dark">` and two `theme-color` metas: `#F5F1EA` (light) and `#16130F` (dark, `media="(prefers-color-scheme: dark)"`).
- **Text on accents:** always `--on-you` / `--on-friend` (dark text). In dark mode the main buttons are green with dark text.
- **Share image:** the share-image canvas in `app.js` always uses the light `--you` green poster, whatever the theme.

**Type** (family / size / weight)
- Display H1: Bricolage 30–34px / 700, line-height 1.05, letter-spacing −0.02em
- Hero number: Bricolage 44–64px / 800, letter-spacing −0.02 to −0.03em
- Stat value: Bricolage 26–34px / 700–800, with the unit at 13–18px / 600
- Card title: Bricolage 16–19px / 700
- Body: Instrument Sans 15–16px / 400–600
- Input text (log box): Instrument Sans 20px / 400, line-height 1.4
- Meta and labels: Instrument Sans 12–14px / 500, `--muted`
- Badge: Instrument Sans 11px / 700, letter-spacing .04em, uppercase

**Radii:** 99px for pills and buttons (48–56px tall buttons are fully rounded) · cards 20–26px · stat tiles 18–20px · value pills 12px · the share poster 28px.

**Spacing:** screen side padding 20–22px · gap between cards 14–18px · card padding 14–20px · chip gap 8px.

**Shadow:** the log card only: `0 1px 0 #E7E0D5, 0 10px 24px rgba(60,40,20,.06)`. Everything else is flat.

## Screens

### 01 Welcome (`welcome.html`)
- **Layout:** the top ~470px is a full-bleed photo (placeholder: friends mid-workout, candid, warm light). Below it, 28px padding, a column with 14px gaps.
- **Content:**
  - Wordmark: a 14px coral dot plus "GymLLM" (Bricolage 17/700)
  - H1: "Log your workout like you'd text a friend."
  - Sub-line: "Lifting, running, yoga, a walk home. Just say what you did and we'll keep track."
- **Pinned to the bottom:**
  - A 56px ink pill, "Continue with Google", with a Google mark
  - Below it: "Free. Private until you add friends." (13px, muted)

### 02 Log (`log.html`, the `#log-form` part)
- **Header:** the date ("Thursday, 24 Sep", muted 14px), then H1 "What did you get up to, {first name}?"
- **White card** (radius 26, padding 20):
  - The textarea has no border and 20px text, with a coral caret. Keep the existing placeholder example.
  - Bottom row, left: the lbs/kg segmented toggle (a `--field` track; the active option is white with a small shadow). Keep `.unit-btn` and `data-unit`.
  - Bottom row, right: the coral "Log it" button, 48px tall.
- **"Or try something like"** chips. Tapping one inserts its text into the textarea.
  - Chips: "Ran 5k in 28 min", "Squats 3×8 at 135", "Yoga, 45 min", "Weighed in at 142"
  - Style: surface-2 background, 1.5px chip-border, 14/500
- **"This week" card:** seven 34px circles for M–S. Logged days are coral, empty days are #F0EAE0, and today is a dashed coral outline. The right side reads "3 of 7 days · 4-week streak". Reuse the data from `_week_strip.html`.
- **Footer row:**
  - "Prefer a form? Add manually" goes to the existing `#classic-form`. Move it to its own sheet or screen.
  - The quota chip ("17 free logs left today") only shows when `config.is_site`.
- **Move off this screen:** "Writing tips" goes into a help sheet, and "Recent sessions" moves to Me or Progress › Sessions.

### 03 Review (`review.html`)
- **Top row:** "‹ Edit text" (re-opens the original text) and "Cancel".
- **Header:** H1 "Here's what we heard.", then the date as an ink pill ("Today · Thu 24 Sep ▾") that opens the date input.
- **Replace the tables with grouped cards:** Lifts, Cardio, Body weight. Each group has a Bricolage 17/700 title and a "+ Add" link (coral-dark, 14/600).
- **Each row:** the exercise name (16/600) with "Remove" on the right, then value pills for weight, sets and reps (or distance and time).
  - Filled pills use `--field`, radius 12, 15/600.
  - Missing values show as a dashed pill, e.g. "+ weight" or "+ time".
  - Tapping a pill edits it inline. Keep the existing `entry-N-*` and `cardio-N-*` input names.
- **Body weight row:** subtitle "Only you see this".
- **Sticky footer:** a 56px ink pill, "Save workout", over a cream fade.

### 04 Home feed (new `main.home`; content from `feed.html` and `_social.html`)
- **Header:** "Evening, {name}" (time-of-day greeting) and a 40px avatar on the right.
- **Week hero card:**
  - Coral background, radius 26
  - "This week" label, then "3 of 7 days" (a 44px number)
  - An ink "4-week streak" pill
  - Seven 8px bars, ink when logged and 18% ink when not
- **"Friends" heading** with a "See all" link to the full feed.
- **Session card** (white, radius 24, padding 16):
  - Header: a 42px avatar, the name (16/600) and "Today · 3 exercises" (13, muted)
  - Rows: the name on the left and "225 lbs · 5×5" on the right in ink-2. PR rows get a coral "NEW BEST" badge.
  - Footer, after a divider: a "High five · N" pill (you-tint background, you-ink text) and an "N comments" pill (`--field`)
  - Below that, a one-line preview of the latest comment
- Friends' avatars use the blue tint; the user's own avatar uses the coral tint.

### 05 Day (`day.html`)
- **Nav:** 40px white round buttons for ‹ and › (greyed out #C9BFB0 when disabled), with the date in the centre (Bricolage 22/700) and "Today" under it.
- **Share poster card** (coral, radius 28, padding 22):
  - Top line: "MAYA · THU 24 SEP" and "GYMLLM" (12/700, tracking .1em)
  - Headline: "8 sets. 3 miles." (64px/800, line-height .9)
  - Rows with 1.5px dividers at 25% ink
  - This is also the look of the generated share image. Update the canvas renderer in `app.js` to match.
- **Stat tiles:** three in a row (Exercises, Reps, Volume), white, radius 18.
- **"From friends" card:** the high-five count and comments.
- **Buttons:** "Share to story" (ink, flexible width) and "Edit" (white, 96px), both 54px tall.
- **Note:** "Body weight is never included when you share."

### 06 Progress (`progress.html` and `_progress_tabs.html`, `_range_filter.html`)
- H1 "Progress".
- **Tabs:** Overview, Sessions, Exercises. The active tab is ink with a 2.5px underline.
- **Range pills:** 7d, 30d, 90d, 1y, All. The active pill is ink with cream text; the rest are white.
- **2×2 stat grid:** Workouts, Streak (weeks), Lifted (lbs volume), Cardio (mi). 34px/800 numbers.
- **"Workouts per week" bar chart:** 8 weeks, rounded 8px bars. Past weeks are #F0E2D8 and the current week is coral.
- **"New personal bests" list:**
  - Left: the name, and under it the date plus "up from X"
  - Right: the new weight (22px/800)
- **Below:** body-weight chart, muscle-group bars, and most-trained list, all in the same card style.

### 07 Friend profile (`profile.html`)
- **Cover:** a 190px blue-tint band with "‹ Friends". A 96px avatar (blue, 5px cream ring) overlaps the bottom edge by 44px.
- **Identity:** the name (Bricolage 28/700), then "@handle · N friends · since Mon YYYY" and the bio.
- **Actions:** "Compare with you" (blue pill, flexible width) and "Friends ✓" (outline). For other relationship states, use the same pill styles with the existing labels (Add friend, Accept, and so on).
- **Stats:** three tiles (Workouts, Sets, Cardio min), captioned "Last 30 days · 6-week streak".
- **Favourites card:** numbered 28px blue-tint circles.

### 08 Compare (`compare.html`)
- **Header:** "You" with a coral avatar, "vs", and the friend's name with a blue avatar.
- **Range pills,** centred.
- **Totals card:** a three-column grid (you | label | them). The leader's number takes their colour's dark ink (you #9A3A1F, them #2A5696).
- **"Lifts you both do":** each lift has a split bar, coral and blue segments sized to each person's best (`flex` ratio), with a legend.
- Muscle split and sessions per week follow the same coral/blue pairing.

## Desktop (≥1024px), section 2 of the design file (D1–D7)
The tokens and components are the same as on mobile. Only the layout changes. Below 1024px, use the mobile screens above.

**Top bar** (replaces the bottom tabs)
- Height 72px, background `--bg`, 1px bottom border `--line`, 40px side padding.
- Left: the wordmark (a 14px coral dot plus "GymLLM", Bricolage 19/700). Then, 40px later, the nav pills Home · Progress · Friends.
  - Pills are 15/600 with 9px 16px padding.
  - The active pill is ink with cream text; the others have no background.
  - Friends carries a coral count badge (20px circle, 12/700) for `social_unseen`.
- Right: a coral "+ Log workout" pill (44px, 15/700) and a 40px avatar that opens a menu (Profile, Settings, Sign out).
  - The Log button goes to Home and focuses the log box.

**Page container:** max-width 1200px, centred, padding 32–36px 40px. H1s are Bricolage 40/700.

- **D1 Welcome:** a two-column 50/50 split. Left: the wordmark at the top, then a vertically centred 64px/700 headline, the sub-line (19px) and the Google button with a note beside it. Right: a full-height photo.
- **D2 Home** (merges mobile 02 Log and 04 Home):
  - Grid of `minmax(0,1fr) 360px`, gap 32px.
  - Main column: the date, the H1 "What did you get up to, {name}?" and the log card.
    - One row inside the card holds the suggestion chips, the lbs/kg toggle and "Log it".
    - Below the card: the "Friends" heading and the feed as a 2-column card grid.
  - Side column: the coral week card (bars labelled M–S), a "Your recent" list (date · summary, linking to Day), and a "Train with friends" invite card with a "Copy invite link" outline button.
- **D3 Review:** a grid of `380px minmax(0,1fr)`.
  - Left: the H1, a "Your words" card with the original text and "Change and try again" (re-parse), and the date pill.
  - Right: the Lifts card, where each row is a grid of name | value pills (+ a note pill) | Remove. Under it, Cardio and Body weight side by side (1.4fr / 1fr).
  - Bottom right: Cancel (text) and "Save workout" (ink, 54px).
- **D4 Day:**
  - Header row: ‹ date › on the left (Bricolage 32/700, with "Today · previous: …" beneath) and "Pick a date" / Edit / Share on the right.
  - Grid of `420px minmax(0,1fr)`. Left: the 4:5 share poster (420×525) with a caption. Right: 4 stat tiles, then a lifts table (Exercise | Weight | Sets × reps, 16px rows, NEW BEST badge), then the "From friends" card with a reply field.
- **D5 Progress:**
  - Header: the H1 and tabs on the left, range pills on the right ("All time" spelled out).
  - A row of 4 stat tiles with 44px numbers.
  - Row 2 (1.6fr / 1fr): workouts per week (12 bars, 180px tall, a day/week/month switch in the card header), then muscle-group bars (10px tall; track #F0EAE0, fill coral).
  - Row 3 (1fr / 1fr): new personal bests, then body weight (weekly average bars in `--line`, with the latest in ink).
- **D6 Profile:**
  - A 160px blue-tint cover. The identity row overlaps it by 56px: a 128px avatar with a 6px cream ring, the name (36/700) with meta and bio on one line, and the action pills on the right.
  - Grid of `320px minmax(0,1fr)`. Left: a 2×2 stat grid, "Last 30 days" and Favourites. Right: "Recent sessions" as 2-column session cards.
- **D7 Compare:**
  - Header: the You-vs-Sam avatars (60px) on the left, range pills on the right.
  - 4 stat tiles, each showing you (left) and them (right), with the leader coloured.
  - Row (1.3fr / 1fr): "Lifts you both do" as 12px split bars, with a gap label ("Sam +20" or "tied"), then the muscle split as paired 7px bars.

**Responsive:** from 1024–1200px the grids keep their structure, and the side columns keep their fixed widths. Below 1024px, switch to the mobile layouts with the bottom tab bar.

## Interactions and state
- Tapping a suggestion chip adds its text to the textarea.
- The unit toggle keeps today's behaviour (`.weight-unit-field`).
- Review value pills become inputs on tap. Remove sets the existing hidden `-delete` checkbox.
- High five toggles the same way the kudos form does now; the pill fills when active.
- Tab bar: Home → `main.home` (feed) · Progress → `main.progress` · + → Log · Friends → `social.friends` · Me → own profile, with Settings reachable from there.
- Transitions: 150ms ease on pill and button background changes, and a scale of 0.97 on press.

## Assets
- Welcome photo: placeholder. It needs a real warm, candid group-training image.
- Avatars: the existing `avatar_url`, falling back to initials on a tint.
- The icons are simple shapes in the mock. Replace them with one consistent rounded icon set, 22px, 2px stroke.
- Update the favicon and wordmark to the coral dot mark.

## Muscle icons (`muscle-icons.js`)
One anatomical figure, cropped and highlighted per group. Preview: `Muscle Icons.dc.html` in this folder (needs `support.js` and `muscle-icons.js` beside it).
- Copy to `static/muscle-icons.js`; load it in `base.html`. No dependencies.
- Lifting groups: chest, back, shoulders, arms, triceps, core, legs, glutes, hamstrings, upper, lower, push, pull, full, cardio.
- Sports and cardio: run, walk, hike, cycle, swim, row, climb, hiit, jumprope, stairs, yoga, pilates, dance, boxing, martial, basketball, soccer, football, volleyball, baseball, tennis, paddle, golf, hockey, ski, sport. These show the full figure with a badge; `variant="glyph"` gives the badge glyph alone for sizes under 24px.
- Free text works anywhere a group is expected: `MuscleIcons.resolve('spin class')` returns `cycle`, and unknown words fall back to `full`. Extend the `WORDS` list in the file to add more.
- Markup: `<muscle-icon group="chest" size="48"></muscle-icon>`. Options: `variant="map|solo"`, `crop="focus|full"`.
- Canvas / server-side: `MuscleIcons.svg(group, {size, variant, crop})` returns an SVG string (use it in the share-image renderer via an Image from a data URL).
- One icon per day: `MuscleIcons.forTags(tags | text)` takes the day's tags or raw log text. Lifting wins on mixed days; one activity gives that activity; several activities give `cardio`.
- Colour: lit muscles use `currentColor`; the rest uses `--mi-base` at `--mi-base-opacity` (default .18). In the app: `color: var(--you)` with `--mi-base: var(--ink)`, `--mi-base-opacity: .1`. On the share card, draw in ink at 140px, top-right, never behind the headline.

## Files
- `muscle-icons.js`: muscle-group, sport and cardio icon set (see above).
- `Muscle Icons.dc.html`: preview of every icon, the text matcher, and share-card placement.
- `theme.css`: the final colour tokens for light and dark. These override any colours in the mockups.
- `GymLLM Mobile Redesign.dc.html`: section 2 is desktop (D1–D7), section 1 is mobile (01–08). Open it with `support.js` in the same folder.
- Target repo files: `templates/base.html`, `welcome.html`, `log.html`, `review.html`, `feed.html`, `_social.html`, `day.html`, `progress.html`, `profile.html`, `compare.html`, `static/style.css`, `static/app.js` (share-image renderer, charts)
