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

# Refuse to push an unexpectedly large payload. This rsyncs the whole repo by
# design (see the header), which means anything left lying in the working tree
# goes too. A bundle unpacked inside the repo while testing left a 2.3GB campaign
# folder here, and the deploy cheerfully started copying it to a droplet with 16GB
# free -- no error, just an rsync that ran for six minutes. The named excludes
# above cover the known shapes; this catches the ones nobody has thought of yet.
MAX_PAYLOAD_MB="${MAX_PAYLOAD_MB:-200}"
echo "==> Checking what would be transferred"
PAYLOAD_BYTES=$(rsync -az --delete --dry-run --stats ${SSH_OPTS[@]+"${SSH_OPTS[@]}"} \
  --exclude '.venv/' --exclude 'web/.venv/' --exclude 'web/scratch/' --exclude 'web/sessions/' \
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '.git/' --exclude '.git' --exclude 'web/.env' \
  --exclude 'examples/*/boltz_output/' --exclude '.sse_cache/' --exclude '.plip_env/' \
  --exclude 'dist/' --exclude '.DS_Store' \
  --exclude '.pixi/' --exclude '*.command' --exclude '*.bmz' \
  --exclude 'boltz_output/' --exclude 'boltz_yamls/' --exclude 'boltz_cif/' \
  --exclude 'boltz_plip/' --exclude 'boltz_dashboard*' --exclude 'boltz_sse_*' \
  ./ "${DROPLET_SSH}:${DROPLET_PATH}/" 2>/dev/null \
  | awk '/Total file size/ {gsub(/,/,"",$4); print $4; exit}')
PAYLOAD_MB=$(( ${PAYLOAD_BYTES:-0} / 1024 / 1024 ))
if [[ "$PAYLOAD_MB" -gt "$MAX_PAYLOAD_MB" ]]; then
  echo "Refusing to deploy: the working tree is ${PAYLOAD_MB}MB, over the ${MAX_PAYLOAD_MB}MB limit."
  echo "Something large is in the repo that probably should not be. The biggest paths:"
  du -sh ./* ./.[a-z]* 2>/dev/null | sort -rh | head -8 | sed 's/^/    /'
  echo "Remove it, add an exclude, or re-run with MAX_PAYLOAD_MB=<n> if it is genuinely wanted."
  exit 1
fi
echo "    ${PAYLOAD_MB}MB to consider (limit ${MAX_PAYLOAD_MB}MB)"

echo "==> Syncing the whole repo to ${DROPLET_SSH}:${DROPLET_PATH}"
rsync -az --delete ${SSH_OPTS[@]+"${SSH_OPTS[@]}"} \
  --exclude '.venv/' --exclude 'web/.venv/' --exclude 'web/scratch/' --exclude 'web/sessions/' \
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '.git/' --exclude '.git' --exclude 'web/.env' \
  --exclude 'examples/*/boltz_output/' --exclude '.sse_cache/' --exclude '.plip_env/' \
  --exclude 'dist/' --exclude '.DS_Store' \
  --exclude '.pixi/' --exclude '*.command' --exclude '*.bmz' \
  --exclude 'boltz_output/' --exclude 'boltz_yamls/' --exclude 'boltz_cif/' \
  --exclude 'boltz_plip/' --exclude 'boltz_dashboard*' --exclude 'boltz_sse_*' \
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
# both venvs, scratch/ and sessions/ so a re-deploy never touches an in-flight
# request's temp dir, an open analysis session, or forces a venv rebuild.
sudo find "${DROPLET_PATH}" \
  -path "${DROPLET_PATH}/.venv" -prune -o \
  -path "${DROPLET_PATH}/web/.venv" -prune -o \
  -path "${DROPLET_PATH}/web/scratch" -prune -o \
  -path "${DROPLET_PATH}/web/sessions" -prune -o \
  -exec chown -h boltzmaker:boltzmaker {} +
# AFTER the chown, never before. These are created as the service user, which can
# only write into web/ once the chown above has run -- doing it first fails with a
# bare "Permission denied", and because this whole remote block runs under `set -e`
# that abort takes the chown and the service restart down with it. The symptom is
# the nastiest kind: rsync has already succeeded, so the deploy looks like it worked
# while the service quietly keeps serving the previous build.
sudo -u boltzmaker mkdir -p "${DROPLET_PATH}/web/scratch" "${DROPLET_PATH}/web/sessions"
sudo systemctl restart boltzmaker-web.service
sudo systemctl --no-pager --lines=2 status boltzmaker-web.service || true
REMOTE

echo "==> Deployed."
