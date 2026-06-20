#!/usr/bin/env bash
# Full VPS deployment for jira-whatsapp middleware.
#
# Deploys from the git clone directory (no copy to /opt unless you set INSTALL_DIR).
# Works with sudo — repo path is resolved from this script's location, not root's $PWD.
#
# Usage (on the VPS):
#   git clone git@github.com:bkyalo/jira-whatsapp.git
#   cd jira-whatsapp
#   cp .env.example .env && nano .env
#   sudo CERTBOT_EMAIL=you@werevu.co.ke ./deploy/deploy.sh
#
# Optional env vars:
#   INSTALL_DIR=/other/path     override install path (default: repo directory)
#   DOMAIN=jira.werevu.co.ke
#   APP_PORT=6060
#   SERVICE_USER=ubuntu         override run user (default: user who ran sudo)
#   SKIP_APT=1                  skip apt install
#   SKIP_CERTBOT=1              HTTP only, no TLS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default: deploy in the directory where the repo was cloned (not /opt)
INSTALL_DIR="${INSTALL_DIR:-$REPO_ROOT}"
DOMAIN="${DOMAIN:-jira.werevu.co.ke}"
APP_PORT="${APP_PORT:-6060}"
# When run via sudo, run the app as the invoking user so git pull still works
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-www-data}}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"

NGINX_SITE="${DOMAIN}.conf"
NGINX_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE}"
SYSTEMD_UNIT="/etc/systemd/system/jira-webhooks.service"
CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"

STEP=0
log()  { STEP=$((STEP + 1)); printf '\n[%d] %s\n' "$STEP" "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

same_path() {
  [[ "$(realpath "$1")" == "$(realpath "$2")" ]]
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Run as root: sudo CERTBOT_EMAIL=you@example.com $0"
  fi
}

install_packages() {
  log "Installing system packages (python3, nginx, certbot, curl, rsync)..."
  if [[ "${SKIP_APT:-0}" == "1" ]]; then
    info "Skipped (SKIP_APT=1)"
    return
  fi
  apt-get update -qq
  apt-get install -y \
    python3 python3-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    curl rsync
  info "Done."
}

ensure_service_user() {
  log "Ensuring service user exists: ${SERVICE_USER}"
  if ! id "${SERVICE_USER}" &>/dev/null; then
    die "User ${SERVICE_USER} does not exist. Create it or set SERVICE_USER=www-data"
  fi
  info "Service will run as: ${SERVICE_USER}"
}

verify_repo_layout() {
  log "Verifying application at ${INSTALL_DIR}..."
  for path in app/main.py config/user_map.json requirements.txt; do
    [[ -f "${INSTALL_DIR}/${path}" ]] || die "Missing ${INSTALL_DIR}/${path}"
  done
  info "Found app/, config/, requirements.txt"
}

sync_app_files() {
  if same_path "${INSTALL_DIR}" "${REPO_ROOT}"; then
    log "Deploying in place at ${INSTALL_DIR} (no file copy)"
    verify_repo_layout
    return
  fi

  log "Copying application to ${INSTALL_DIR}..."
  mkdir -p "${INSTALL_DIR}"
  rsync -a --delete \
    --exclude '.venv' \
    --exclude '.env' \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "${REPO_ROOT}/app" \
    "${REPO_ROOT}/config" \
    "${REPO_ROOT}/requirements.txt" \
    "${INSTALL_DIR}/"
  info "Synced from ${REPO_ROOT}"
}

setup_env() {
  log "Setting up environment file ${INSTALL_DIR}/.env"

  if [[ -f "${INSTALL_DIR}/.env" ]]; then
    info "Keeping existing ${INSTALL_DIR}/.env"
  elif [[ -f "${INSTALL_DIR}/.env.example" ]]; then
    cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
    info "Created from .env.example — edit secrets before production use"
  else
    die "No .env or .env.example in ${INSTALL_DIR}"
  fi

  if grep -q '^PORT=' "${INSTALL_DIR}/.env"; then
    sed -i "s/^PORT=.*/PORT=${APP_PORT}/" "${INSTALL_DIR}/.env"
  else
    echo "PORT=${APP_PORT}" >> "${INSTALL_DIR}/.env"
  fi

  if ! grep -q '^HOST=' "${INSTALL_DIR}/.env"; then
    echo "HOST=127.0.0.1" >> "${INSTALL_DIR}/.env"
  fi

  chown "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/.env"
  chmod 600 "${INSTALL_DIR}/.env"
  info "Permissions: 600, owner ${SERVICE_USER}"
}

validate_env() {
  log "Validating required .env variables..."
  local env_file="${INSTALL_DIR}/.env"
  local missing=0
  for key in JIRA_WEBHOOK_SECRET OPENWA_API_KEY OPENWA_SESSION_ID; do
    local val
    val="$(grep "^${key}=" "$env_file" | cut -d= -f2- || true)"
    if [[ -z "$val" || "$val" == *"change-me"* || "$val" == *"your_"* ]]; then
      info "WARNING: ${key} is missing or still a placeholder"
      missing=1
    else
      info "OK: ${key}"
    fi
  done
  if [[ "$missing" -eq 1 ]]; then
    info "Edit ${INSTALL_DIR}/.env then run: sudo systemctl restart jira-webhooks"
  fi
}

setup_venv() {
  log "Creating Python virtualenv and installing dependencies..."
  if [[ ! -d "${INSTALL_DIR}/.venv" ]]; then
    sudo -u "${SERVICE_USER}" python3 -m venv "${INSTALL_DIR}/.venv"
    info "Created ${INSTALL_DIR}/.venv"
  else
    info "Reusing existing venv"
  fi
  sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -q --upgrade pip
  sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -q -r "${INSTALL_DIR}/requirements.txt"
  info "Dependencies installed"
}

fix_permissions() {
  log "Setting permissions on ${INSTALL_DIR}..."

  if same_path "${INSTALL_DIR}" "${REPO_ROOT}"; then
    # In-place deploy: only take ownership of runtime files, leave .git for the developer
    chown -R "${SERVICE_USER}:${SERVICE_USER}" \
      "${INSTALL_DIR}/.venv" \
      "${INSTALL_DIR}/.env" \
      "${INSTALL_DIR}/config"
    info "In-place deploy — .git left owned by you; .venv/.env/config owned by ${SERVICE_USER}"
  else
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
    info "Owner: ${SERVICE_USER}:${SERVICE_USER}"
  fi
}

install_systemd() {
  log "Creating systemd service: ${SYSTEMD_UNIT}"
  sed \
    -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
    "${SCRIPT_DIR}/systemd/jira-webhooks.service" > "${SYSTEMD_UNIT}"

  info "WorkingDirectory: ${INSTALL_DIR}"
  info "ExecStart:        ${INSTALL_DIR}/.venv/bin/python -m app.main"
  info "EnvironmentFile:  ${INSTALL_DIR}/.env"
  info "User:             ${SERVICE_USER}"

  systemctl daemon-reload
  systemctl enable jira-webhooks
  systemctl restart jira-webhooks
  info "Enabled and started: jira-webhooks"
  systemctl --no-pager status jira-webhooks || true
}

copy_nginx_config() {
  local src="$1"
  sed \
    -e "s|jira.werevu.co.ke|${DOMAIN}|g" \
    -e "s|127.0.0.1:6060|127.0.0.1:${APP_PORT}|g" \
    "${src}" > "${NGINX_AVAILABLE}"
  ln -sf "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
  info "Installed: ${NGINX_AVAILABLE}"
  nginx -t
  systemctl reload nginx
  info "Nginx reloaded"
}

install_nginx_http_bootstrap() {
  log "Configuring Nginx (HTTP bootstrap for ${DOMAIN})..."
  copy_nginx_config "${SCRIPT_DIR}/nginx/jira.werevu.co.ke.http.conf"
}

install_nginx_ssl() {
  log "Configuring Nginx (HTTPS for ${DOMAIN})..."
  copy_nginx_config "${SCRIPT_DIR}/nginx/jira.werevu.co.ke.conf"
}

setup_tls() {
  log "Setting up TLS for ${DOMAIN}..."

  if [[ "${SKIP_CERTBOT:-0}" == "1" ]]; then
    info "Skipped certbot (SKIP_CERTBOT=1) — HTTP only"
    install_nginx_http_bootstrap
    return
  fi

  if [[ -f "${CERT_PATH}" ]]; then
    info "Certificate already exists: ${CERT_PATH}"
    install_nginx_ssl
    return
  fi

  install_nginx_http_bootstrap

  if [[ -z "${CERTBOT_EMAIL}" ]]; then
    info "WARNING: CERTBOT_EMAIL not set — skipping certificate request."
    info "Re-run with: sudo CERTBOT_EMAIL=you@example.com $0"
    return
  fi

  info "Requesting certificate via certbot..."
  certbot certonly --nginx \
    -d "${DOMAIN}" \
    --non-interactive \
    --agree-tos \
    -m "${CERTBOT_EMAIL}"

  install_nginx_ssl
  info "HTTPS enabled"
}

verify_health() {
  log "Health check on 127.0.0.1:${APP_PORT}..."
  for i in $(seq 1 20); do
    if curl -sf "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
      info "OK — app responding (attempt ${i})"
      curl -s "http://127.0.0.1:${APP_PORT}/health"
      echo
      return 0
    fi
    sleep 1
  done
  die "App not responding. Debug: journalctl -u jira-webhooks -n 50 --no-pager"
}

print_summary() {
  cat <<EOF

================================================================================
 Deployment complete
================================================================================

 Paths (resolved automatically — no /opt copy unless you set INSTALL_DIR)
   Repository:    ${REPO_ROOT}
   Install dir:   ${INSTALL_DIR}
   Service user:  ${SERVICE_USER}

 Files
   Environment:   ${INSTALL_DIR}/.env
   User map:      ${INSTALL_DIR}/config/user_map.json
   Virtualenv:    ${INSTALL_DIR}/.venv

 Systemd
   Unit file:     ${SYSTEMD_UNIT}
   Status:        systemctl status jira-webhooks
   Logs:          journalctl -u jira-webhooks -f
   Restart:       systemctl restart jira-webhooks

 Nginx
   Config:        ${NGINX_AVAILABLE}

 URLs
   Health:        https://${DOMAIN}/health
   Webhook:       https://${DOMAIN}/webhooks/jira

 Redeploy after git pull (from ${INSTALL_DIR}):
   git pull && sudo CERTBOT_EMAIL=${CERTBOT_EMAIL:-you@example.com} ./deploy/deploy.sh

================================================================================
EOF
}

main() {
  printf 'Deploying jira-whatsapp\n'
  info "Repository:  ${REPO_ROOT}"
  info "Install dir:   ${INSTALL_DIR}"
  info "Service user:  ${SERVICE_USER}"
  require_root
  install_packages
  ensure_service_user
  sync_app_files
  setup_env
  validate_env
  setup_venv
  fix_permissions
  install_systemd
  setup_tls
  verify_health
  print_summary
}

main "$@"
