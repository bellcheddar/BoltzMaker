"""Gunicorn entrypoint: gunicorn --config deploy/gunicorn.conf.py wsgi:app"""

from boltzmaker_web.app import create_app

app = create_app()
