"""Gunicorn entrypoint: `gunicorn wsgi:app`."""

from gymllm import create_app

app = create_app()
