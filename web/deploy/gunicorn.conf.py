"""Gunicorn config for the boltzmaker-web service. Referenced by boltzmaker-web.service."""
import os

bind = os.environ.get("BIND_ADDR", "127.0.0.1:8003")
workers = int(os.environ.get("WEB_WORKERS", "3"))
worker_class = "sync"
# 300s, not AlphaFraud's 60s -- a sync worker here blocks on both a large (up to
# 200MB) upload body AND the subsequent subprocess.run() for `analyze` (whose own
# runner.py timeout is already 300s; gunicorn's worker timeout must be at least that
# long or gunicorn kills the worker before BoltzMaker.py itself would time out).
timeout = 300
graceful_timeout = 30
keepalive = 5
# Log to stdout/stderr so journald captures everything (journalctl -u boltzmaker-web).
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
proc_name = "boltzmaker-web"
