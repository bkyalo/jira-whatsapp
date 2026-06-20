import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from app.auth import verify_webhook_secret as _verify_secret
from app.config import Settings, get_settings
from app.handlers import process_event
from app.logging_setup import setup_logging
from app.mapper import UserMapper
from app.models import JiraWebhookPayload
from app.openwa_client import OpenWAClient
from app.payload_normalize import normalize_jira_payload
from app.webhook_payload_log import WebhookPayloadLogger

logger = logging.getLogger(__name__)

_payload_adapter: TypeAdapter[JiraWebhookPayload] = TypeAdapter(JiraWebhookPayload)

UNPROCESSABLE = getattr(
    status,
    "HTTP_422_UNPROCESSABLE_CONTENT",
    status.HTTP_422_UNPROCESSABLE_ENTITY,
)

mapper: UserMapper | None = None
openwa_client: OpenWAClient | None = None
payload_logger: WebhookPayloadLogger | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mapper, openwa_client, payload_logger
    settings = get_settings()
    setup_logging(settings.log_level)
    mapper = UserMapper(settings.user_map_file)
    openwa_client = OpenWAClient(settings)
    payload_logger = WebhookPayloadLogger(settings.webhook_payload_log_file)
    logger.info("Jira-WhatsApp middleware started")
    yield
    logger.info("Jira-WhatsApp middleware stopped")


app = FastAPI(
    title="Jira-to-WhatsApp Middleware",
    description="Receives Jira Automation webhooks and forwards alerts via OpenWA",
    version="1.0.0",
    lifespan=lifespan,
)


def require_webhook_secret(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_jira_webhook_secret: Annotated[str | None, Header(alias="X-Jira-Webhook-Secret")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    _verify_secret(request, x_jira_webhook_secret, authorization, settings)


def _get_mapper() -> UserMapper:
    assert mapper is not None
    return mapper


def _get_openwa() -> OpenWAClient:
    assert openwa_client is not None
    return openwa_client


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/reload-map", dependencies=[Depends(require_webhook_secret)])
async def reload_user_map(user_mapper: UserMapper = Depends(_get_mapper)) -> dict[str, str]:
    user_mapper.reload()
    return {"status": "reloaded"}


@app.post(
    "/webhooks/jira",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_webhook_secret)],
)
async def jira_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    user_mapper: UserMapper = Depends(_get_mapper),
    client: OpenWAClient = Depends(_get_openwa),
) -> JSONResponse:
    query = dict(request.query_params)
    client_ip = request.client.host if request.client else None
    raw_payload: dict[str, Any]

    try:
        body = await request.json()
        if not isinstance(body, dict):
            if payload_logger:
                payload_logger.write(
                    raw_payload={"_non_object_body": body},
                    normalized_payload={},
                    query_params=query,
                    client_ip=client_ip,
                    status="rejected_invalid_body",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON body must be an object",
            )
        raw_payload = body
    except HTTPException:
        raise
    except Exception:
        if payload_logger:
            payload_logger.write(
                raw_payload={"_error": "invalid_json"},
                normalized_payload={},
                query_params=query,
                client_ip=client_ip,
                status="rejected_invalid_json",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    normalized = normalize_jira_payload(raw_payload, query)

    try:
        _payload_adapter.validate_python(normalized)
    except ValidationError as exc:
        errors = exc.errors()
        logger.error(
            "Webhook validation failed: %s payload_keys=%s event=%s task_id=%s",
            errors,
            list(normalized.keys()),
            normalized.get("event"),
            normalized.get("task_id"),
        )
        if payload_logger:
            payload_logger.write(
                raw_payload=raw_payload,
                normalized_payload=normalized,
                query_params=query,
                client_ip=client_ip,
                status="rejected_validation",
                validation_errors=errors,
            )
        raise HTTPException(status_code=UNPROCESSABLE, detail=errors)

    if payload_logger:
        payload_logger.write(
            raw_payload=raw_payload,
            normalized_payload=normalized,
            query_params=query,
            client_ip=client_ip,
            status="accepted",
        )

    background_tasks.add_task(process_event, normalized, user_mapper, client)
    return JSONResponse(content={"status": "accepted"}, status_code=status.HTTP_202_ACCEPTED)


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
