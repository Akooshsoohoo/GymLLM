# GymLLM

A local-first, web-based workout logger and search tool powered by OpenAI's GPT.

---

## What is GymLLM?

GymLLM lets you log workouts in plain language, have them parsed and normalized using OpenAI's API, review and confirm what gets saved, and search/filter all your workout history from a web browser.  
All data is local by default.

---

## Requirements

- Python 3.8 or newer (tested on 3.10+)
- pip
- An OpenAI API key

---

## Installation & Setup

1. Clone the repository:

   git clone https://github.com/Akooshsoohoo/gymllm.git
   cd gymllm

2. Install dependencies:

   pip install flask openai pandas python-dotenv

3. Set up your OpenAI API key:

   - Go to https://platform.openai.com/api-keys and create an API key.
   - Create a file named `.env` in the project directory.
   - Add this line to `.env`:

     OPENAI_API_KEY=sk-...

   (Replace `sk-...` with your actual OpenAI API key.)

---

## Running the App

Start the web server with:

   python app.py

- The app runs at http://localhost:5000.
- No need for any cloud deployment or extra setup for local use.

---

## Usage

1. Go to http://localhost:5000.
2. Enter your workout in plain English in the form (e.g., "bench 185 for 5x5, lat pulldowns 3x10").
3. Review and confirm the parsed and canonicalized result. Edit and re-parse as needed.
4. When satisfied, approve and save to log.
5. To search/filter your workout history, go to `/search` (or click the navigation link).

---

## Customization

- Exercises/Tags:  
  Edit `exerciseList.csv` and `taggedExerciseList.csv` to control canonical exercise names and tags.
- Styling:  
  Edit `static/style.css` for custom appearance.
- All logs are stored in `workoutLog.csv` in the project directory.

---

## Project Structure

- `app.py` — Main Flask web app (UI, routes, logging, search)
- `main.py` — LLM parsing and normalization logic
- `exerciseList.csv` — Canonical exercise names
- `taggedExerciseList.csv` — Canonical names and their tags
- `workoutLog.csv` — Your logged workouts (auto-created)
- `static/style.css` — All UI styling
- `.env` — Your (private) OpenAI API key

---

## Notes

- Your OpenAI API key is required to use the app.  
  The key is read from `.env` and is never uploaded or shared.
- All data is local.  
  Nothing is sent anywhere except to OpenAI’s API for parsing.
- If you want to deploy online or share with others, you will need to handle your API key and user authentication accordingly.
- Do not commit your `.env` or `workoutLog.csv` to git.  
  Add them to `.gitignore`.

---

## Example: .gitignore

.env
workoutLog.csv

---

## Example: .env

OPENAI_API_KEY=sk-...

---

## Example: exerciseList.csv

bench press
lat pulldown
dumbbell curl
triceps rope pushdown
shoulder press
...

---

## Example: taggedExerciseList.csv

exercise,tags
bench press,chest;push;compound
lat pulldown,back;pull;compound;lats
dumbbell curl,biceps;pull;isolation
triceps rope pushdown,triceps;push;isolation
shoulder press,shoulders;push;compound
...

---

## License

MIT License. Use at your own risk.

---

## Support

For issues or feature requests, open an issue or PR on the repository.
