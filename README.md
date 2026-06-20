# Jira-to-WhatsApp Middleware

Lightweight FastAPI service that receives Jira Automation webhooks and forwards notifications to WhatsApp via [OpenWA](https://whatsapp.werevu.co.ke/api/docs).

## What it does

| Jira event | WhatsApp recipient |
|------------|-------------------|
| Task assigned | New assignee |
| Task completed (Done) | Issue creator |
| New comment | Assignee + creator (comment author excluded) |

## Requirements

- Python 3.11+
- OpenWA instance with an active WhatsApp session and API key
- Jira Cloud Automation (Send web request action)

## Quick start (local)

```bash
cd JiraWebhooks
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your secrets and OpenWA session ID
```

Edit `config/user_map.json` with Jira **account IDs** and/or emails:

```json
{
  "emails": {
    "alice@company.co.ke": "+254712345678"
  },
  "account_ids": {
    "712020:f64eab9b-dbae-4fd5-b9a6-31ed5bff3116": "+254757135612"
  }
}
```

Use `account_ids` when your team roster comes from Jira (recommended). Add `emails` later if you prefer email-based lookup.

Run the server:

```bash
python -m app.main
# or: uvicorn app.main:app --host 127.0.0.1 --port 6060
```

Health check: `GET http://127.0.0.1:6060/health`

## Environment variables

| Variable | Description |
|----------|-------------|
| `JIRA_WEBHOOK_SECRET` | Shared secret; Jira sends this in `X-Jira-Webhook-Secret` |
| `OPENWA_BASE_URL` | OpenWA API base URL (use `http://127.0.0.1:3000` on same VPS) |
| `OPENWA_API_KEY` | OpenWA API key (`X-API-Key` header) |
| `OPENWA_SESSION_ID` | UUID of the connected WhatsApp session |
| `USER_MAP_PATH` | Path to email→phone JSON (default: `config/user_map.json`) |
| `HOST` | Bind address (default: `127.0.0.1`) |
| `PORT` | Bind port (default: `6060`) |
| `LOG_LEVEL` | `INFO`, `DEBUG`, etc. |
| `OPENWA_MAX_RETRIES` | Retries on send failure (default: `2`) |
| `OPENWA_RETRY_DELAY_SECONDS` | Base delay between retries (default: `1.0`) |
| `JIRA_EMAIL` | Atlassian account email (for downloading attachment images) |
| `JIRA_API_TOKEN` | [Atlassian API token](https://id.atlassian.com/manage-profile/security/api-tokens) |

## Custom fields & images

All event payloads support these **optional** issue fields:

| JSON field | Jira source | Notes |
|------------|-------------|--------|
| `site_name` | `{{issue.customfield_XXXXX}}` | Replace with your Site Name custom field ID |
| `module` | `{{issue.summary}}` | Your summary = Module name |
| `description` | `{{issue.description}}` | Plain text / ADF stripped in WhatsApp |
| `issue_url` | `{{issue.url}}` | Link to the issue |
| `image_url` | attachment URL (see below) | Sent as WhatsApp image if available |

**Find custom field IDs:** Jira → Settings → Issues → Custom fields → Site Name → … → inspect ID in URL (`customfield_10086`).

**Images:** Jira attachment URLs require auth. Set `JIRA_EMAIL` + `JIRA_API_TOKEN` in `.env`. In Automation, pass the attachment content URL, e.g. from a related lookup or hardcoded pattern:

```json
"image_url": "https://your-domain.atlassian.net/rest/api/3/attachment/content/ATTACHMENT_ID"
```

Public image URLs (no Atlassian host) work without Jira credentials.

### Example — task assigned with Site Name, Module, description, image

```json
{
  "event": "task_assigned",
  "task_id": "{{issue.key}}",
  "module": "{{issue.summary}}",
  "site_name": "{{issue.customfield_10086}}",
  "description": "{{issue.description}}",
  "issue_url": "{{issue.url}}",
  "image_url": "{{issue.attachment.url}}",
  "assigned_to_name": "{{issue.assignee.displayName}}",
  "assigned_to_account_id": "{{issue.assignee.accountId}}"
}
```

WhatsApp message example:

```
📋 Task assigned: PROJ-123
Assigned to: Ben TITO
Site: Nairobi HQ
Module: HVAC maintenance
Description: Check unit 4 compressor...
https://yourorg.atlassian.net/browse/PROJ-123
```

If `image_url` is set and reachable, an image follows the text message.

## OpenWA setup

1. **Create an API key** (admin):

```bash
curl -X POST https://whatsapp.werevu.co.ke/api/auth/api-keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_ADMIN_KEY" \
  -d '{"name": "jira-middleware", "role": "operator"}'
```

Save the returned `apiKey` — it is shown only once.

2. **Create and start a session**:

```bash
curl -X POST https://whatsapp.werevu.co.ke/api/sessions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"name": "jira-notifications"}'

curl -X POST https://whatsapp.werevu.co.ke/api/sessions/{SESSION_ID}/start \
  -H "X-API-Key: YOUR_API_KEY"

curl https://whatsapp.werevu.co.ke/api/sessions/{SESSION_ID}/qr \
  -H "X-API-Key: YOUR_API_KEY"
```

Scan the QR code with WhatsApp. Confirm session status is `ready`:

```bash
curl https://whatsapp.werevu.co.ke/api/sessions/{SESSION_ID} \
  -H "X-API-Key: YOUR_API_KEY"
```

3. Put `SESSION_ID` and `apiKey` into your `.env`.

On the same VPS as OpenWA, set `OPENWA_BASE_URL=http://127.0.0.1:3000` so traffic stays internal.

## VPS deployment

One command on the server — deploys **in the git clone directory** (path detected from the script, not `/opt`). Creates venv, `.env`, **systemd service**, **nginx config**, and **TLS cert**.

```bash
git clone git@github.com:bkyalo/jira-whatsapp.git
cd jira-whatsapp
cp .env.example .env && nano .env
sudo CERTBOT_EMAIL=you@werevu.co.ke ./deploy/deploy.sh
```

The script resolves the repo path automatically (even when run with `sudo`), runs the service as **your user** (via `$SUDO_USER`), and leaves `.git` owned by you so `git pull` keeps working.

### What `deploy/deploy.sh` creates

| Step | What happens |
|------|----------------|
| 1 | Installs `python3`, `nginx`, `certbot`, `curl`, `rsync` |
| 2 | Verifies app files in the clone directory (no copy to `/opt`) |
| 3 | Creates `.env` in the repo if missing, sets `PORT=6060` |
| 4 | Validates `JIRA_WEBHOOK_SECRET`, `OPENWA_API_KEY`, `OPENWA_SESSION_ID` |
| 5 | Creates `.venv` + `pip install` in the clone directory |
| 6 | Writes `/etc/systemd/system/jira-webhooks.service` pointing at **your clone path** |
| 7 | Configures nginx + Let's Encrypt TLS |
| 8 | Runs health check on `127.0.0.1:6060` |

**Files on the server (example: `/home/ubuntu/jira-whatsapp/`):**

```
/home/ubuntu/jira-whatsapp/                  # your git clone (app stays here)
/home/ubuntu/jira-whatsapp/.venv/            # Python virtualenv
/home/ubuntu/jira-whatsapp/.env              # secrets
/etc/systemd/system/jira-webhooks.service    # points at clone path above
/etc/nginx/sites-available/jira.werevu.co.ke.conf
```

**Redeploy after `git pull`:**

```bash
cd ~/jira-whatsapp
git pull
sudo CERTBOT_EMAIL=you@werevu.co.ke ./deploy/deploy.sh
```

**Optional env overrides:**

| Variable | Default | Description |
|----------|---------|-------------|
| `INSTALL_DIR` | repo directory | Override install path (e.g. `/opt/jira-webhooks`) |
| `DOMAIN` | `jira.werevu.co.ke` | Public hostname |
| `APP_PORT` | `6060` | App port |
| `SERVICE_USER` | user who ran `sudo` | systemd run user |
| `CERTBOT_EMAIL` | — | Let's Encrypt email (required for HTTPS on first run) |
| `SKIP_APT=1` | — | Skip `apt-get install` |
| `SKIP_CERTBOT=1` | — | HTTP only, no TLS |

### Manual deployment (alternative)

If you prefer to set things up by hand instead of the script:

```bash
sudo mkdir -p /opt/jira-webhooks
sudo cp -r app config requirements.txt /opt/jira-webhooks/
sudo cp .env /opt/jira-webhooks/.env
cd /opt/jira-webhooks
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create `/etc/systemd/system/jira-webhooks.service`:

```ini
[Unit]
Description=Jira to WhatsApp middleware
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/jira-webhooks
EnvironmentFile=/opt/jira-webhooks/.env
ExecStart=/opt/jira-webhooks/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 6060
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable jira-webhooks
sudo systemctl start jira-webhooks
sudo systemctl status jira-webhooks
```

## Nginx reverse proxy

Use a **dedicated subdomain** for this middleware — separate from OpenWA:

| Host | Role |
|------|------|
| `jira.werevu.co.ke` | Jira sends webhooks **here** (this Python app on port `6060`) |
| `whatsapp.werevu.co.ke` | OpenWA only — middleware **calls out** to send messages |

A ready-made config is in [`deploy/nginx/jira.werevu.co.ke.conf`](deploy/nginx/jira.werevu.co.ke.conf).

Add a DNS A record for `jira.werevu.co.ke` pointing to the same VPS, then:

```bash
sudo cp deploy/nginx/jira.werevu.co.ke.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/jira.werevu.co.ke.conf /etc/nginx/sites-enabled/
sudo certbot certonly --nginx -d jira.werevu.co.ke   # skip if cert already exists
sudo nginx -t && sudo systemctl reload nginx
```

**Jira webhook URL** (what you put in Jira Automation):

```
https://jira.werevu.co.ke/webhooks/jira
```

Health check: `https://jira.werevu.co.ke/health`

## Jira Automation rules

Create three rules (or one rule with branching). Each uses **Send web request**:

- **Method:** POST
- **URL:** `https://jira.werevu.co.ke/webhooks/jira?secret=YOUR_SECRET` (easiest for Jira — see auth below)
- **Content-Type:** application/json

### Authentication (Jira often skips custom headers)

Jira Automation frequently **does not send** custom headers unless configured exactly. The middleware accepts **any one** of:

| Method | Jira setup |
|--------|------------|
| **Query param (recommended for Jira)** | URL: `https://jira.werevu.co.ke/webhooks/jira?secret=YOUR_SECRET&event=task_assigned` |
| Header | `X-Jira-Webhook-Secret: YOUR_SECRET` |
| Bearer | `Authorization: Bearer YOUR_SECRET` |

Jira may append `&triggeredByUser=...` to the URL automatically — that is fine.

**Custom headers in Jira** (if your plan supports it) — add as JSON in the web request action:

```json
{
  "Content-Type": "application/json",
  "X-Jira-Webhook-Secret": "YOUR_SECRET"
}
```

### Rule 1 — Task assigned

- **Trigger:** Issue assigned / Assignee field changed
- **Body:**

```json
{
  "event": "task_assigned",
  "task_id": "{{issue.key}}",
  "module": "{{issue.summary}}",
  "site_name": "{{issue.customfield_XXXXX}}",
  "description": "{{issue.description}}",
  "issue_url": "{{issue.url}}",
  "image_url": "",
  "assigned_to_name": "{{issue.assignee.displayName}}",
  "assigned_to_account_id": "{{issue.assignee.accountId}}"
}
```

### Rule 2 — Task completed

- **Trigger:** Issue transitioned to Done (or your completed status)
- **Body:**

```json
{
  "event": "task_completed",
  "task_id": "{{issue.key}}",
  "title": "{{issue.summary}}",
  "created_by_name": "{{issue.reporter.displayName}}",
  "created_by_email": "{{issue.reporter.emailAddress}}",
  "created_by_account_id": "{{issue.reporter.accountId}}",
  "completed_by": "{{initiator.displayName}}"
}
```

### Rule 3 — New comment

- **Trigger:** Comment added
- **Body:**

```json
{
  "event": "new_comment",
  "task_id": "{{issue.key}}",
  "title": "{{issue.summary}}",
  "comment_author": "{{comment.author.displayName}}",
  "comment_author_email": "{{comment.author.emailAddress}}",
  "comment_author_account_id": "{{comment.author.accountId}}",
  "comment_text": "{{comment.body}}",
  "involved_parties": {
    "creator_email": "{{issue.reporter.emailAddress}}",
    "creator_account_id": "{{issue.reporter.accountId}}",
    "assignee_email": "{{issue.assignee.emailAddress}}",
    "assignee_account_id": "{{issue.assignee.accountId}}"
  }
}
```

## Manual testing (curl)

Replace `YOUR_SECRET` with your webhook secret.

**Task assigned:**

```bash
curl -X POST http://127.0.0.1:6060/webhooks/jira \
  -H "Content-Type: application/json" \
  -H "X-Jira-Webhook-Secret: YOUR_SECRET" \
  -d '{
    "event": "task_assigned",
    "task_id": "PROJ-123",
    "title": "Fix login bug",
    "assigned_to_name": "Alice",
    "assigned_to_email": "alice@company.co.ke"
  }'
```

**Task completed:**

```bash
curl -X POST http://127.0.0.1:6060/webhooks/jira \
  -H "Content-Type: application/json" \
  -H "X-Jira-Webhook-Secret: YOUR_SECRET" \
  -d '{
    "event": "task_completed",
    "task_id": "PROJ-123",
    "title": "Fix login bug",
    "created_by_name": "Bob",
    "created_by_email": "bob@company.co.ke",
    "completed_by": "Alice"
  }'
```

**New comment:**

```bash
curl -X POST http://127.0.0.1:6060/webhooks/jira \
  -H "Content-Type: application/json" \
  -H "X-Jira-Webhook-Secret: YOUR_SECRET" \
  -d '{
    "event": "new_comment",
    "task_id": "PROJ-123",
    "title": "Fix login bug",
    "comment_author": "Carol",
    "comment_author_email": "carol@company.co.ke",
    "comment_text": "Looks good, merging.",
    "involved_parties": {
      "creator_email": "bob@company.co.ke",
      "assignee_email": "alice@company.co.ke"
    }
  }'
```

Expected response: `202` with `{"status":"accepted"}`. Check server logs for delivery status.

## Admin endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Liveness check |
| `/webhooks/jira` | POST | `X-Jira-Webhook-Secret` | Receive Jira events |
| `/admin/reload-map` | POST | `X-Jira-Webhook-Secret` | Reload `user_map.json` without restart |

## Logs

Each delivery is logged as:

```
[task_assigned] success -> +2547***5678
```

API keys are never logged. Unmapped emails log `no_mapping_for_email`.

## Project layout

```
JiraWebhooks/
├── app/
│   ├── main.py           # FastAPI routes
│   ├── config.py         # Settings from .env
│   ├── models.py         # Pydantic payload schemas
│   ├── mapper.py         # Email → phone → chatId
│   ├── formatters.py     # Message text templates
│   ├── openwa_client.py  # OpenWA HTTP client
│   ├── handlers.py       # Event routing logic
│   └── logging_setup.py
├── config/user_map.json
├── .env.example
└── requirements.txt
```
