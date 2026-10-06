"""The local Flask for the iOS simulator, with a canned stand-in for the model, so
the whole log, review and save loop runs without a SITE_LLM_API_KEY.

    source .venv/bin/activate && python ios/scripts/dev_server.py

Serves http://localhost:5001, where a Debug build in the simulator looks. Whatever
you type, it "hears" a bench press and a run; text containing "nothing" hears
nothing. Only ever runs on the SQLite database in instance/.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gymllm import create_app  # noqa: E402

HEARD = {
    "date": None,
    "exercises": [
        {"exercise": "bench press", "weight": "185 lbs", "sets": 3, "reps": [5, 5, 5], "notes": ""}
    ],
    "cardio": [{"activity": "run", "distance": "2 miles", "duration": "", "notes": ""}],
    "bodyweight": None,
}
TAGS = {"tags": ["chest", "push"]}


class CannedClient:
    def complete_json(self, system, user):
        if user.startswith("Exercise: "):  # a tagging call, not the reading of a log
            return TAGS
        if "nothing" in user.lower():
            return {"date": None, "exercises": []}
        return HEARD

    def list_models(self):
        return ["canned"]


app = create_app()
if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
    sys.exit("Refusing to run: DATABASE_URL is set. This server is for the local SQLite only.")
if app.config.get("SITE_LLM") is None:
    app.config["SITE_LLM"] = {
        "provider": "groq",
        "model": "canned",
        "api_key": "canned-local-only",
        "base_url": "",
        "daily_limit": 200,
    }
    app.config["LLM_CLIENT_FACTORY"] = lambda config: CannedClient()
    print(" * No SITE_LLM_API_KEY: using the canned reader")

if __name__ == "__main__":
    # Loopback only, and no debugger: nothing here needs to be reachable from the network.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5001)), debug=False)
