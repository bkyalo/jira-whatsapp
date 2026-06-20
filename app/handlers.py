import logging
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.formatters import (
    format_new_comment,
    format_task_assigned,
    format_task_completed,
)
from app.logging_setup import mask_phone
from app.mapper import UserMapper
from app.models import (
    JiraWebhookPayload,
    NewCommentPayload,
    TaskAssignedPayload,
    TaskCompletedPayload,
)
from app.openwa_client import OpenWAClient

logger = logging.getLogger(__name__)

_payload_adapter: TypeAdapter[JiraWebhookPayload] = TypeAdapter(JiraWebhookPayload)


@dataclass(frozen=True)
class Recipient:
    email: str = ""
    account_id: str = ""


async def process_event(
    raw_payload: dict[str, Any],
    mapper: UserMapper,
    openwa: OpenWAClient,
) -> None:
    try:
        payload = _payload_adapter.validate_python(raw_payload)
    except ValidationError as exc:
        logger.error("Invalid webhook payload: %s", exc)
        return

    if isinstance(payload, TaskAssignedPayload):
        await _handle_task_assigned(payload, mapper, openwa)
    elif isinstance(payload, TaskCompletedPayload):
        await _handle_task_completed(payload, mapper, openwa)
    elif isinstance(payload, NewCommentPayload):
        await _handle_new_comment(payload, mapper, openwa)


async def _send_to_recipient(
    event: str,
    recipient: Recipient,
    text: str,
    mapper: UserMapper,
    openwa: OpenWAClient,
) -> None:
    if not recipient.email and not recipient.account_id:
        logger.warning("[%s] skip: empty recipient identity", event)
        return

    phone = mapper.lookup(email=recipient.email, account_id=recipient.account_id)
    if not phone:
        logger.warning(
            "[%s] no_mapping email=%s account_id=%s",
            event,
            recipient.email or "-",
            recipient.account_id or "-",
        )
        return

    success = await openwa.send_to_phone(phone, text, mapper)
    status = "success" if success else "fail"
    logger.info("[%s] %s -> %s", event, status, mask_phone(phone))


async def _handle_task_assigned(
    payload: TaskAssignedPayload,
    mapper: UserMapper,
    openwa: OpenWAClient,
) -> None:
    text = format_task_assigned(payload)
    await _send_to_recipient(
        "task_assigned",
        Recipient(
            email=payload.assigned_to_email,
            account_id=payload.assigned_to_account_id,
        ),
        text,
        mapper,
        openwa,
    )


async def _handle_task_completed(
    payload: TaskCompletedPayload,
    mapper: UserMapper,
    openwa: OpenWAClient,
) -> None:
    text = format_task_completed(payload)
    await _send_to_recipient(
        "task_completed",
        Recipient(
            email=payload.created_by_email,
            account_id=payload.created_by_account_id,
        ),
        text,
        mapper,
        openwa,
    )


def _recipient_key(recipient: Recipient) -> str:
    if recipient.account_id:
        return f"id:{recipient.account_id}"
    return f"email:{recipient.email.strip().lower()}"


async def _handle_new_comment(
    payload: NewCommentPayload,
    mapper: UserMapper,
    openwa: OpenWAClient,
) -> None:
    text = format_new_comment(payload)
    author = Recipient(
        email=payload.comment_author_email,
        account_id=payload.comment_author_account_id,
    )
    author_key = _recipient_key(author) if (author.email or author.account_id) else ""

    candidates = [
        Recipient(
            email=payload.involved_parties.creator_email,
            account_id=payload.involved_parties.creator_account_id,
        ),
        Recipient(
            email=payload.involved_parties.assignee_email,
            account_id=payload.involved_parties.assignee_account_id,
        ),
    ]

    recipients: list[Recipient] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.email and not candidate.account_id:
            continue
        key = _recipient_key(candidate)
        if key == author_key:
            continue
        if key not in seen:
            seen.add(key)
            recipients.append(candidate)

    if not recipients:
        logger.warning(
            "[new_comment] skip: no eligible recipients task_id=%s",
            payload.task_id,
        )
        return

    for recipient in recipients:
        await _send_to_recipient("new_comment", recipient, text, mapper, openwa)
