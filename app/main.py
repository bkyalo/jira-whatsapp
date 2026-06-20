import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.handlers import process_event
from app.logging_setup import setup_logging
from app.mapper import UserMapper
from app.models import JiraWebhookPayload
from app.openwa_client import OpenWAClient
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)

_payload_adapter: TypeAdapter[JiraWebhookPayload] = TypeAdapter(JiraWebhookPayload)

mapper: UserMapper | None = None
openwa_client: OpenWAClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mapper, openwa_client
    settings = get_settings()
    setup_logging(settings.log_level)
    mapper = UserMapper(settings.user_map_file)
    openwa_client = OpenWAClient(settings)
    logger.info("Jira-WhatsApp middleware started")
    yield
    logger.info("Jira-WhatsApp middleware stopped")


app = FastAPI(
    title="Jira-to-WhatsApp Middleware",
    description="Receives Jira Automation webhooks and forwards alerts via OpenWA",
    version="1.0.0",
    lifespan=lifespan,
)


def verify_webhook_secret(
    x_jira_webhook_secret: str | None = Header(default=None, alias="X-Jira-Webhook-Secret"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_jira_webhook_secret or x_jira_webhook_secret != settings.jira_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook secret",
        )


def _get_mapper() -> UserMapper:
    assert mapper is not None
    return mapper


def _get_openwa() -> OpenWAClient:
    assert openwa_client is not None
    return openwa_client


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/reload-map", dependencies=[Depends(verify_webhook_secret)])
async def reload_user_map(user_mapper: UserMapper = Depends(_get_mapper)) -> dict[str, str]:
    user_mapper.reload()
    return {"status": "reloaded"}


@app.post(
    "/webhooks/jira",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_webhook_secret)],
)
async def jira_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    user_mapper: UserMapper = Depends(_get_mapper),
    client: OpenWAClient = Depends(_get_openwa),
) -> JSONResponse:
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    try:
        _payload_adapter.validate_python(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        )

    background_tasks.add_task(process_event, payload, user_mapper, client)
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
