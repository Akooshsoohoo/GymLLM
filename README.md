# GymLLM

Log workouts in plain English. GymLLM sends your text to the LLM of your choice
(OpenAI, Anthropic, Gemini, Groq, OpenRouter, a local Ollama or LM Studio, or any
OpenAI-compatible server), shows you the parsed sets and reps to review and edit,
then saves them to your personal log. Search and edit the log, and see per-exercise
history with a progress chart.

Sign-in is via Google. Each user only ever sees their own entries.

## How it works

1. Sign in with Google.
2. On **LLM Settings**, pick a provider, a model, and (for hosted providers) your
   API key. Hit **Test connection** to check it works. The key lives in a signed
   cookie in your browser; the server forwards it to the provider when you parse a
   workout and never stores it.
3. On **Log Workout**, type something like
   `yesterday: bench 185 for 5x5, lat pulldowns 3x10, felt strong`.
4. Review the parsed table, fix anything, adjust the date, and save.
5. **Search / Edit Log** lists everything newest first with in-place editing.
   **History** shows every exercise you have done and a chart of your top weight
   per session.

## Running locally

Requirements: Python 3.12, a Google OAuth client.

```bash
git clone https://github.com/Akooshsoohoo/GymLLM.git
cd GymLLM
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
copy .env.example .env          # cp on macOS/Linux
```

Fill in `.env`:

| Variable | Notes |
|---|---|
| `FLASK_SECRET_KEY` | Any long random string. `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | From [Google Cloud Console](https://console.cloud.google.com/apis/credentials): create an *OAuth client ID* of type *Web application* and add `http://localhost:5000/login/google/authorized` as an authorised redirect URI. |
| `DATABASE_URL` | Optional locally. Defaults to a SQLite file in `instance/`. |
| `OAUTHLIB_INSECURE_TRANSPORT=1` | Local only, so OAuth works over plain `http://localhost`. |

Then:

```bash
python app.py
```

Open <http://localhost:5000>.

### Using a local model

Install [Ollama](https://ollama.com), run `ollama pull llama3.2`, keep Ollama
running, and choose **Ollama (local)** on the settings page. Local providers only
work when GymLLM itself is running on the same machine, because the server is what
talks to the model. If you deploy GymLLM and still want a local model, expose it
through a tunnel and use the **Custom (OpenAI-compatible)** provider with that URL.

### Tests and lint

```bash
pytest -q
ruff check . && ruff format --check .
```

Tests use an in-memory SQLite database and a fake LLM client; nothing touches the
network or your real database.

## Deploying to Render

`render.yaml` describes the service: Python 3.12, `gunicorn wsgi:app`, health
check on `/healthz`. Set these environment variables on the service:

- `FLASK_ENV=production` (enables Secure cookies, requires `DATABASE_URL`)
- `FLASK_SECRET_KEY`
- `DATABASE_URL` (Render Postgres; `postgres://` URLs are rewritten automatically)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, with
  `https://<your-domain>/login/google/authorized` added as a redirect URI.

Do **not** set `OAUTHLIB_INSECURE_TRANSPORT` in production.

The database table is created on startup if missing. The schema is unchanged from
earlier versions, so existing data keeps working.

## Project layout

```
app.py / wsgi.py          entrypoints (dev server / gunicorn)
gymllm/
  __init__.py             create_app() factory
  config.py               environment -> Flask config
  auth.py                 Google sign-in, session caching, login_required
  routes.py               all pages: log, review, confirm, search, history, settings
  parsing.py              system prompt + normalisation of LLM output
  exercises.py            canonical exercise list, matching, LLM tag fallback
  llm/providers.py        provider registry + per-browser LLMConfig
  llm/client.py           OpenAI-compatible and Anthropic adapters, error mapping
  models.py               Workout table
data/taggedExerciseList.csv   canonical names and tags (edit to customise)
templates/, static/       Jinja templates, CSS, and the small front-end script
tests/                    pytest suite
```

## Adding a provider

Most providers expose an OpenAI-compatible endpoint. Add an entry to `PROVIDERS`
in `gymllm/llm/providers.py` with its base URL, default model, and whether it needs
a key. Providers with their own SDK (like Anthropic) get an adapter class in
`gymllm/llm/client.py` implementing `complete_json(system, user)`.

## License

MIT.
