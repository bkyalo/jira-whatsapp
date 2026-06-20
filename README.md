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
# or: uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Health check: `GET http://127.0.0.1:8080/health`

## Environment variables

| Variable | Description |
|----------|-------------|
| `JIRA_WEBHOOK_SECRET` | Shared secret; Jira sends this in `X-Jira-Webhook-Secret` |
| `OPENWA_BASE_URL` | OpenWA API base URL (use `http://127.0.0.1:3000` on same VPS) |
| `OPENWA_API_KEY` | OpenWA API key (`X-API-Key` header) |
| `OPENWA_SESSION_ID` | UUID of the connected WhatsApp session |
| `USER_MAP_PATH` | Path to email→phone JSON (default: `config/user_map.json`) |
| `HOST` | Bind address (default: `127.0.0.1`) |
| `PORT` | Bind port (default: `8080`) |
| `LOG_LEVEL` | `INFO`, `DEBUG`, etc. |
| `OPENWA_MAX_RETRIES` | Retries on send failure (default: `2`) |
| `OPENWA_RETRY_DELAY_SECONDS` | Base delay between retries (default: `1.0`) |

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

## VPS deployment (systemd)

Install on the same server as OpenWA:

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
ExecStart=/opt/jira-webhooks/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
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
| `jira.werevu.co.ke` | Jira sends webhooks **here** (this Python app) |
| `whatsapp.werevu.co.ke` | OpenWA only — middleware **calls out** to send messages |

Add a DNS A record for `jira.werevu.co.ke` pointing to the same VPS, then create `/etc/nginx/sites-available/jira-webhooks`:

```nginx
server {
    listen 80;
    server_name jira.werevu.co.ke;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name jira.werevu.co.ke;

    ssl_certificate     /etc/letsencrypt/live/jira.werevu.co.ke/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jira.werevu.co.ke/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and obtain TLS (if not already):

```bash
sudo ln -s /etc/nginx/sites-available/jira-webhooks /etc/nginx/sites-enabled/
sudo certbot certonly --nginx -d jira.werevu.co.ke
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
- **URL:** `https://jira.werevu.co.ke/webhooks/jira`
- **Header:** `X-Jira-Webhook-Secret: <your secret>`
- **Content-Type:** application/json

### Rule 1 — Task assigned

- **Trigger:** Issue assigned / Assignee field changed
- **Body:**

```json
{
  "event": "task_assigned",
  "task_id": "{{issue.key}}",
  "title": "{{issue.summary}}",
  "assigned_to_name": "{{issue.assignee.displayName}}",
  "assigned_to_email": "{{issue.assignee.emailAddress}}",
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
curl -X POST http://127.0.0.1:8080/webhooks/jira \
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
curl -X POST http://127.0.0.1:8080/webhooks/jira \
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
curl -X POST http://127.0.0.1:8080/webhooks/jira \
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
