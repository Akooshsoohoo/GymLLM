"""Development entrypoint: `python app.py`. Production uses wsgi.py + gunicorn."""

import os

from gymllm import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=not app.config.get("IS_PRODUCTION"))
