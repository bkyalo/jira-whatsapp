"""Normalize Jira Automation / webhook payloads into our flat schema."""

from __future__ import annotations

import re
from typing import Any


def _snake_key(key: str) -> str:
    s1 = re.sub(r"([A-Z])", r"_\1", key)
    return s1.replace("-", "_").lower().lstrip("_")


def _snake_dict(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        sk = _snake_key(key) if key != "event" else key
        if isinstance(value, dict):
            out[sk] = _snake_dict(value)
        elif isinstance(value, list):
            out[sk] = value
        else:
            out[sk] = value
    return out


def _user_account_id(user: dict[str, Any] | None) -> str:
    if not user:
        return ""
    return str(user.get("accountId") or user.get("account_id") or "")


def _user_display_name(user: dict[str, Any] | None) -> str:
    if not user:
        return ""
    return str(user.get("displayName") or user.get("display_name") or "")


def _flatten_issue(payload: dict[str, Any]) -> None:
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        return

    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}

    payload.setdefault("task_id", issue.get("key") or issue.get("id") or "")
    payload.setdefault("module", fields.get("summary") or "")
    payload.setdefault("title", fields.get("summary") or "")
    payload.setdefault("description", _adf_to_text(fields.get("description")))

    assignee = fields.get("assignee")
    if isinstance(assignee, dict):
        payload.setdefault("assigned_to_name", _user_display_name(assignee))
        payload.setdefault("assigned_to_account_id", _user_account_id(assignee))
        payload.setdefault("assigned_to_email", assignee.get("emailAddress") or assignee.get("email_address") or "")

    reporter = fields.get("reporter") or fields.get("creator")
    if isinstance(reporter, dict):
        payload.setdefault("created_by_name", _user_display_name(reporter))
        payload.setdefault("created_by_account_id", _user_account_id(reporter))
        payload.setdefault("created_by_email", reporter.get("emailAddress") or reporter.get("email_address") or "")

    for key, value in fields.items():
        if key.startswith("customfield_") and value not in (None, "", {}):
            if payload.get("site_name"):
                continue
            if isinstance(value, dict):
                payload.setdefault("site_name", value.get("value") or value.get("name") or str(value))
            else:
                payload.setdefault("site_name", str(value))


def _adf_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        for block in value.get("content", []):
            if isinstance(block, dict):
                for node in block.get("content", []):
                    if isinstance(node, dict) and node.get("text"):
                        parts.append(str(node["text"]))
        return " ".join(parts).strip()
    return str(value)


def _apply_query_params(payload: dict[str, Any], query: dict[str, str]) -> None:
    if not payload.get("event") and query.get("event"):
        payload["event"] = query["event"]

    triggered = query.get("triggeredByUser") or query.get("triggered_by_user")
    if triggered:
        payload.setdefault("triggered_by_account_id", triggered)
        if payload.get("event") == "task_completed":
            payload.setdefault("completed_by", triggered)
        if payload.get("event") == "new_comment":
            payload.setdefault("comment_author_account_id", triggered)


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("body", "data", "payload", "webhook"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            merged = {**inner, **{k: v for k, v in payload.items() if k != key}}
            return merged
    return payload


def normalize_jira_payload(
    raw: dict[str, Any],
    query_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = _snake_dict(_unwrap(raw))
    _flatten_issue(payload)
    _apply_query_params(payload, dict(query_params or {}))

    if payload.get("module") and not payload.get("title"):
        payload["title"] = payload["module"]
    if payload.get("title") and not payload.get("module"):
        payload["module"] = payload["title"]

    return payload
