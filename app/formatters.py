import re
from typing import Protocol

from app.models import NewCommentPayload, TaskAssignedPayload, TaskCompletedPayload

MAX_COMMENT_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 300


class HasIssueFields(Protocol):
    task_id: str
    title: str
    site_name: str
    module: str
    description: str
    issue_url: str

    def module_label(self, fallback_title: str = "") -> str: ...


def strip_html(text: str) -> str:
    """Remove HTML/ADF-like tags and collapse whitespace."""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def truncate(text: str, max_len: int = MAX_COMMENT_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _issue_detail_lines(payload: HasIssueFields) -> list[str]:
    lines: list[str] = []
    if payload.site_name.strip():
        lines.append(f"Site: {payload.site_name.strip()}")
    lines.append(f"Module: {payload.module_label(payload.title)}")
    if payload.description.strip():
        desc = truncate(strip_html(payload.description), MAX_DESCRIPTION_LENGTH)
        lines.append(f"Description: {desc}")
    if payload.issue_url.strip():
        lines.append(payload.issue_url.strip())
    return lines


def _join_header(headline: str, payload: HasIssueFields) -> str:
    parts = [headline, *_issue_detail_lines(payload)]
    return "\n".join(parts)


def format_task_assigned(payload: TaskAssignedPayload) -> str:
    name = payload.assigned_to_name or "you"
    headline = f"📋 Task assigned: {payload.task_id}\nAssigned to: {name}"
    return _join_header(headline, payload)


def format_task_completed(payload: TaskCompletedPayload) -> str:
    completed_by = payload.completed_by or "someone"
    headline = f"✅ {payload.task_id} completed\nCompleted by: {completed_by}"
    return _join_header(headline, payload)


def format_new_comment(payload: NewCommentPayload) -> str:
    author = payload.comment_author or "Someone"
    body = truncate(strip_html(payload.comment_text))
    headline = f"💬 New comment on {payload.task_id} by {author}:\n\"{body}\""
    return _join_header(headline, payload)
