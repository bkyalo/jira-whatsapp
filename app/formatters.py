import re

from app.models import NewCommentPayload, TaskAssignedPayload, TaskCompletedPayload

MAX_COMMENT_LENGTH = 500


def strip_html(text: str) -> str:
    """Remove HTML/ADF-like tags and collapse whitespace."""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def truncate(text: str, max_len: int = MAX_COMMENT_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def format_task_assigned(payload: TaskAssignedPayload) -> str:
    name = payload.assigned_to_name or "you"
    return (
        f"📋 Task assigned: {payload.task_id} — {payload.title}\n"
        f"Assigned to: {name}"
    )


def format_task_completed(payload: TaskCompletedPayload) -> str:
    completed_by = payload.completed_by or "someone"
    return (
        f"✅ {payload.task_id} completed\n"
        f'"{payload.title}"\n'
        f"Completed by: {completed_by}"
    )


def format_new_comment(payload: NewCommentPayload) -> str:
    author = payload.comment_author or "Someone"
    body = truncate(strip_html(payload.comment_text))
    return (
        f"💬 New comment on {payload.task_id} by {author}:\n"
        f'"{body}"'
    )
