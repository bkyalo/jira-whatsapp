import asyncio
import logging

import httpx

from app.config import Settings
from app.mapper import UserMapper

logger = logging.getLogger(__name__)


class OpenWAClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.openwa_base_url.rstrip("/")
        self._session_id = settings.openwa_session_id
        self._headers = {"X-API-Key": settings.openwa_api_key}

    def _messages_url(self, path: str) -> str:
        return f"{self._base_url}/api/sessions/{self._session_id}/messages{path}"

    async def check_number(self, phone_digits: str) -> bool | None:
        """Return True/False if WhatsApp knows the number, None if check unavailable."""
        url = (
            f"{self._base_url}/api/sessions/{self._session_id}"
            f"/contacts/check/{phone_digits}"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=self._headers)
                if response.status_code == 200:
                    data = response.json()
                    return bool(data.get("exists", data.get("isRegistered", True)))
        except httpx.HTTPError as exc:
            logger.warning("Number check failed for %s: %s", phone_digits[:4] + "***", exc)
        return None

    async def send_text(self, chat_id: str, text: str) -> bool:
        url = self._messages_url("/send-text")
        payload = {"chatId": chat_id, "text": text}
        max_retries = self._settings.openwa_max_retries
        delay = self._settings.openwa_retry_delay_seconds

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=self._headers,
                    )
                    if response.status_code in (200, 201):
                        return True
                    logger.error(
                        "OpenWA send-text failed (attempt %d): status=%s body=%s",
                        attempt + 1,
                        response.status_code,
                        response.text[:200],
                    )
            except httpx.HTTPError as exc:
                logger.error(
                    "OpenWA send-text error (attempt %d): %s",
                    attempt + 1,
                    exc,
                )

            if attempt < max_retries:
                await asyncio.sleep(delay * (attempt + 1))

        return False

    async def send_to_phone(self, phone: str, text: str, mapper: UserMapper) -> bool:
        chat_id = mapper.e164_to_chat_id(phone)
        digits = chat_id.split("@")[0]
        exists = await self.check_number(digits)
        if exists is False:
            logger.warning("Phone not registered on WhatsApp: chat_id=%s", chat_id)
            return False
        return await self.send_text(chat_id, text)
