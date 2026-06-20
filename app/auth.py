import logging

from fastapi import HTTPException, Request, status

from app.config import Settings

logger = logging.getLogger(__name__)


def extract_webhook_secret(
    request: Request,
    header_secret: str | None,
    authorization: str | None,
) -> str | None:
    if header_secret and header_secret.strip():
        return header_secret.strip()

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token

    for key in ("secret", "webhook_secret"):
        value = request.query_params.get(key)
        if value and value.strip():
            return value.strip()

    return None


def verify_webhook_secret(
    request: Request,
    x_jira_webhook_secret: str | None = None,
    authorization: str | None = None,
    settings: Settings | None = None,
) -> None:
    assert settings is not None

    provided = extract_webhook_secret(request, x_jira_webhook_secret, authorization)
    if provided and provided == settings.jira_webhook_secret:
        return

    logger.warning(
        "Webhook auth failed: header=%s authorization=%s query_secret=%s",
        "yes" if x_jira_webhook_secret else "no",
        "yes" if authorization else "no",
        "yes" if request.query_params.get("secret") or request.query_params.get("webhook_secret") else "no",
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing webhook secret",
    )
