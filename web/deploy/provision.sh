#!/usr/bin/env bash
# One-time droplet provisioning for boltzmaker.mdeller.com. Run as root ON the droplet,
# AFTER the code is present at /opt/boltzmaker (push it first with web/deploy/deploy.sh
# from your Mac -- it rsyncs the WHOLE repo, not just web/, preserving BoltzMaker.py at
# the repo root and web/ nested one level under it exactly as it is here. Flattening
# web/* up into $APP_DIR breaks path resolution -- see runner.py's own module
# docstring for the exact chatPDB/chem_sage bug this mirrors).
#
#   sudo SERVER_NAME=boltzmaker.mdeller.com bash /opt/boltzmaker/web/deploy/provision.sh
#
# Idempotent: safe to re-run. Installs system packages, a service user, TWO Python
# venvs plus the optional conda-forge PLIP environment (see below), the systemd web
# service + scratch-cleanup timer, the nginx site, and a Let's Encrypt certificate.
set -euo pipefail

APP_DIR=/opt/boltzmaker
WEB_DIR="$APP_DIR/web"
APP_USER=boltzmaker
BIND_ADDR="${BIND_ADDR:-127.0.0.1:8003}"

if [[ -f "$WEB_DIR/.env" ]]; then
  set -a; # shellcheck disable=SC1091
  source "$WEB_DIR/.env"; set +a
fi
SERVER_NAME="${SERVER_NAME:-boltzmaker.mdeller.com}"

echo "==> BoltzMaker web provisioning for ${SERVER_NAME}"

if [[ $EUID -ne 0 ]]; then echo "Run as root (sudo)."; exit 1; fi
if [[ ! -f "$APP_DIR/BoltzMaker.py" ]]; then
  echo "No code at $APP_DIR. Push it first: bash web/deploy/deploy.sh (from your Mac)."; exit 1
fi
if [[ ! -f "$WEB_DIR/wsgi.py" ]]; then
  echo "web/ looks flattened or missing under $APP_DIR -- deploy.sh must preserve the"
  echo "real repo nesting (web/ one level under BoltzMaker.py), never flatten it up."
  exit 1
fi

echo "==> Installing system packages (nginx/certbot already present droplet-wide from"
echo "    earlier apps -- apt-get install on an already-installed package is a no-op)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip python3-dev build-essential \
  nginx certbot python3-certbot-nginx rsync

echo "==> Creating service user '${APP_USER}'"
id -u "$APP_USER" &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$WEB_DIR/scratch" "$WEB_DIR/sessions"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Building BoltzMaker's own trimmed venv (repo root .venv/ -- NOT via"
echo "    'BoltzMaker.py setup', which would pull in boltz+torch. This app never runs"
echo "    real GPU inference, so torch/boltz are deliberately never installed here --"
echo "    generate/preflight/analyze all work fine without them (every torch/boltz"
echo "    reference in BoltzMaker.py is a function-local lazy import, confirmed"
echo "    directly against the source), and the footprint stays ~500MB instead of 1.4GB."
if [[ ! -x "$APP_DIR/.venv/bin/python3" ]]; then
  sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet \
  rich pandas openpyxl pyyaml rdkit matplotlib psutil scipy gemmi biopython plotly reportlab requests

echo "==> Building the PLIP interaction-analysis environment (repo root .plip_env/ --"
echo "    conda-forge python+gemmi+openbabel+pymol-open-source via micromamba, ~1-1.5GB,"
echo "    used by 'analyze' for protein-ligand interaction detection. Optional -- analyze"
echo "    gracefully skips interaction analysis if this env isn't present."
# Built as root, NOT `sudo -u boltzmaker` like the two venvs above -- confirmed
# empirically that micromamba's package extraction fails under Ubuntu 24.04's
# apparmor_restrict_unprivileged_userns=1 hardening for an unprivileged user with no
# AppArmor profile ("cannot set current path: Permission denied" on nearly every
# package), but works fine as root. Loosening that sysctl would weaken every app on
# this shared droplet against a real local-privesc surface, so build as root (same as
# the apt-get install above) and hand ownership to boltzmaker afterward instead.
if [[ ! -x "$APP_DIR/.plip_env/env/bin/python" ]]; then
  rm -rf "$APP_DIR/.plip_env"
  "$APP_DIR/.venv/bin/python3" "$APP_DIR/BoltzMaker.py" setup-plip --yes
  chown -R "$APP_USER:$APP_USER" "$APP_DIR/.plip_env"
else
  echo "    reusing existing .plip_env"
fi

echo "==> Building the Flask-serving venv (web/.venv/ -- flask/gunicorn only, a"
echo "    deliberately separate dependency set from BoltzMaker's own, see"
echo "    web/requirements.txt's own comment)"
if [[ ! -x "$WEB_DIR/.venv/bin/python3" ]]; then
  sudo -u "$APP_USER" python3 -m venv "$WEB_DIR/.venv"
fi
sudo -u "$APP_USER" "$WEB_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$WEB_DIR/.venv/bin/pip" install --quiet -r "$WEB_DIR/requirements.txt"

echo "==> Installing systemd units"
cp "$WEB_DIR/deploy/boltzmaker-web.service"        /etc/systemd/system/
cp "$WEB_DIR/deploy/boltzmaker-scratch-clean.service" /etc/systemd/system/
cp "$WEB_DIR/deploy/boltzmaker-scratch-clean.timer"   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now boltzmaker-web.service
systemctl enable --now boltzmaker-scratch-clean.timer

echo "==> Installing nginx snippets"
mkdir -p /etc/nginx/snippets
cp "$WEB_DIR/deploy/nginx-snippet-boltzmaker-proxy.conf" /etc/nginx/snippets/boltzmaker-proxy.conf
if [[ ! -f /etc/nginx/snippets/long-cache.conf ]]; then
  echo "    WARNING: /etc/nginx/snippets/long-cache.conf not found (expected from"
  echo "    mdeller-landing's own deploy.sh --provision run) -- installing this app's"
  echo "    own copy so the nginx site below doesn't fail to load."
  cat > /etc/nginx/snippets/long-cache.conf <<'EOF'
add_header Cache-Control "public, max-age=31536000, immutable" always;
access_log off;
EOF
fi

echo "==> Installing nginx site"
sed -e "s|__SERVER_NAME__|${SERVER_NAME}|g" -e "s|__BIND_ADDR__|${BIND_ADDR}|g" \
  "$WEB_DIR/deploy/nginx-boltzmaker.conf" > /etc/nginx/sites-available/boltzmaker
ln -sf /etc/nginx/sites-available/boltzmaker /etc/nginx/sites-enabled/boltzmaker
nginx -t && systemctl reload nginx

echo "==> Requesting/deploying TLS certificate (certbot)"
# Always run certbot --nginx, never skip based on "certificate already exists" --
# the nginx site file above is unconditionally re-templated from source on every
# run (plain HTTP only, no SSL block), so a stale skip-if-cert-exists check here
# would leave a freshly re-templated vhost with no SSL directives at all,
# breaking HTTPS for this app (nginx then falls back to serving *some other*
# vhost's cert on port 443 for this hostname -- a real production incident hit
# by exactly this bug on the very first re-provision of this app). certbot's own
# `--nginx` plugin already reuses a still-valid certificate instead of
# re-requesting one (avoiding Let's Encrypt rate limits), so this is safe and
# correctly idempotent to run unconditionally.
# Retried: certbot's own systemd renewal timer (certbot.timer, droplet-wide, covers
# every vhost's cert) can grab certbot's lock at the same moment this runs -- hit
# empirically ("Another instance of Certbot is already running") on this exact step.
# A failure here is worse than usual since the vhost file was just unconditionally
# re-templated to plain HTTP above, so leaving it un-retried means shipping a
# provision.sh run that silently leaves this app's HTTPS broken.
certbot_ok=0
for attempt in 1 2 3; do
  if certbot --nginx -d "$SERVER_NAME" --non-interactive --agree-tos \
       -m "${CERTBOT_EMAIL:-marc@marcdeller.com}" --redirect; then
    certbot_ok=1
    break
  fi
  echo "    certbot attempt ${attempt}/3 failed, retrying in 10s..."
  sleep 10
done
if [[ "$certbot_ok" -ne 1 ]]; then
  echo "    certbot failed after 3 attempts (DNS not pointed yet? renewal-timer lock"
  echo "    contention?). ${SERVER_NAME} has NO SSL config right now -- re-run:"
  echo "    certbot --nginx -d ${SERVER_NAME}"
  exit 1
fi

# Certbot's `listen 443 ssl;` lines don't enable HTTP/2 on nginx 1.24 -- add it
# ourselves, idempotently. This is droplet-wide-shared-port-443-critical: nginx's
# http2 option is per listen address:port, shared across every server block on that
# socket -- a vhost that skips this can destabilize others already on port 443.
if grep -q "listen.*443 ssl" /etc/nginx/sites-available/boltzmaker && \
   ! grep -q "listen.*443 ssl http2" /etc/nginx/sites-available/boltzmaker; then
  echo "==> Enabling HTTP/2"
  python3 - <<'PYEOF'
import re
p = "/etc/nginx/sites-available/boltzmaker"
text = open(p).read()
text = re.sub(
    r'listen ((?:\[::\]:)?443) ssl( ipv6only=on)?;',
    lambda m: f'listen {m.group(1)} ssl http2{m.group(2) or ""};',
    text,
)
open(p, "w").write(text)
PYEOF
  nginx -t && systemctl reload nginx
fi

echo "==> Done. Status:"
systemctl --no-pager --lines=3 status boltzmaker-web || true
echo "    Site: https://${SERVER_NAME}/"
echo "    Healthcheck: curl -s https://${SERVER_NAME}/healthz"
