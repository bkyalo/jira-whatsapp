import base64
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

IMAGE_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
)


def _jira_headers(settings: Settings) -> dict[str, str]:
    if not settings.jira_email or not settings.jira_api_token:
        return {}
    token = base64.b64encode(
        f"{settings.jira_email}:{settings.jira_api_token}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def _guess_mimetype(url: str, content_type: str | None) -> str:
    if content_type:
        mime = content_type.split(";")[0].strip().lower()
        if mime in IMAGE_CONTENT_TYPES:
            return mime
    lower = url.lower()
    for ext, mime in (
        (".png", "image/png"),
        (".gif", "image/gif"),
        (".webp", "image/webp"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
    ):
        if lower.endswith(ext):
            return mime
    return "image/jpeg"


async def resolve_image_payload(
    image_url: str,
    settings: Settings,
) -> dict[str, Any] | None:
    """
    Prepare OpenWA send-image payload.
    Public URLs pass through; Jira/Atlassian URLs are downloaded with API token if configured.
    """
    url = image_url.strip()
    if not url:
        return None

    needs_auth = any(
        host in url
        for host in ("atlassian.net", "atlassian.com", "jira.com")
    )
    headers = _jira_headers(settings) if needs_auth else {}

    if needs_auth and not headers:
        logger.warning(
            "image_url requires Jira auth but JIRA_EMAIL/JIRA_API_TOKEN not set — skipping image"
        )
        return None

    if not needs_auth:
        return {"url": url}

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                logger.error(
                    "Failed to download Jira image: status=%s url=%s",
                    response.status_code,
                    url[:120],
                )
                return None
            content_type = response.headers.get("content-type")
            mimetype = _guess_mimetype(url, content_type)
            if content_type and content_type.split(";")[0].strip().lower() not in IMAGE_CONTENT_TYPES:
                logger.warning("Attachment may not be an image: content-type=%s", content_type)
            return {
                "base64": base64.b64encode(response.content).decode(),
                "mimetype": mimetype,
            }
    except httpx.HTTPError as exc:
        logger.error("Image download error: %s", exc)
        return None
