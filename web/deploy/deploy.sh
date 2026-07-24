#!/usr/bin/env bash
# Push BoltzMaker (the WHOLE repo, not just web/) from your Mac to the droplet and
# restart the web service. Run from the repo root: bash web/deploy/deploy.sh
#
# Reads DROPLET_SSH / DROPLET_PATH from web/.env (see web/.env.example). Idempotent;
# excludes both venvs, generated/example-output directories, and secrets so the
# server's own state (and its already-built venvs) are never clobbered by a re-deploy.
#
# Critical: this rsyncs the REPO ROOT, never just web/ -- BoltzMaker.py's own
# VENV_DIR = SCRIPT_DIR / ".venv" is hardcoded relative to its own location, and
# runner.py resolves BoltzMaker.py/.venv paths relative to its own __file__ up to the
# real repo root. Flattening web/* up a directory breaks both (the exact bug class
# chatPDB's own deploy docs warn about -- see web/boltzmaker_web/runner.py's docstring).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f web/.env ]]; then set -a; source web/.env; set +a; fi
DROPLET_SSH="${DROPLET_SSH:-}"
DROPLET_PATH="${DROPLET_PATH:-/opt/boltzmaker}"
SSH_KEY="${SSH_KEY:-}"

if [[ -z "$DROPLET_SSH" ]]; then
  echo "DROPLET_SSH is not set. Copy web/.env.example to web/.env and fill it in."; exit 1
fi

SSH_OPTS=()
[[ -n "$SSH_KEY" ]] && SSH_OPTS=(-e "ssh -i ${SSH_KEY/#\~/$HOME}")

echo "==> Syncing the whole repo to ${DROPLET_SSH}:${DROPLET_PATH}"
rsync -az --delete ${SSH_OPTS[@]+"${SSH_OPTS[@]}"} \
  --exclude '.venv/' --exclude 'web/.venv/' --exclude 'web/scratch/' \
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '.git/' --exclude 'web/.env' \
  --exclude 'examples/*/boltz_output/' --exclude '.sse_cache/' --exclude '.plip_env/' \
  --exclude 'dist/' \
  ./ "${DROPLET_SSH}:${DROPLET_PATH}/"

echo "==> Installing web dependencies + restarting service on the droplet"
SSH_CMD=(ssh)
[[ -n "$SSH_KEY" ]] && SSH_CMD=(ssh -i "${SSH_KEY/#\~/$HOME}")
"${SSH_CMD[@]}" "$DROPLET_SSH" bash -s <<REMOTE
set -euo pipefail
cd "${DROPLET_PATH}"
if [[ ! -x .venv/bin/python3 || ! -x web/.venv/bin/python3 ]]; then
  echo "One or both venvs missing -- run web/deploy/provision.sh as root first."; exit 0
fi
sudo -u boltzmaker env PIP_NO_CACHE_DIR=1 ./web/.venv/bin/pip install --quiet -r web/requirements.txt
# rsync (run as root) leaves new files root-owned; chown them to boltzmaker, but PRUNE
# both venvs and scratch/ so a re-deploy never touches an in-flight request's temp dir
# or forces a venv rebuild.
sudo find "${DROPLET_PATH}" \
  -path "${DROPLET_PATH}/.venv" -prune -o \
  -path "${DROPLET_PATH}/web/.venv" -prune -o \
  -path "${DROPLET_PATH}/web/scratch" -prune -o \
  -exec chown boltzmaker:boltzmaker {} +
sudo systemctl restart boltzmaker-web.service
sudo systemctl --no-pager --lines=2 status boltzmaker-web.service || true
REMOTE

echo "==> Deployed."
