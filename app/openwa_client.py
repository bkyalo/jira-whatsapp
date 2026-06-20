import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings
from app.mapper import UserMapper
from app.media import resolve_image_payload

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

    async def _post_with_retry(self, path: str, payload: dict[str, Any]) -> bool:
        url = self._messages_url(path)
        max_retries = self._settings.openwa_max_retries
        delay = self._settings.openwa_retry_delay_seconds

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=self._headers,
                    )
                    if response.status_code in (200, 201):
                        return True
                    logger.error(
                        "OpenWA %s failed (attempt %d): status=%s body=%s",
                        path,
                        attempt + 1,
                        response.status_code,
                        response.text[:200],
                    )
            except httpx.HTTPError as exc:
                logger.error("OpenWA %s error (attempt %d): %s", path, attempt + 1, exc)

            if attempt < max_retries:
                await asyncio.sleep(delay * (attempt + 1))

        return False

    async def send_text(self, chat_id: str, text: str) -> bool:
        return await self._post_with_retry("/send-text", {"chatId": chat_id, "text": text})

    async def send_image(
        self,
        chat_id: str,
        image: dict[str, Any],
        caption: str = "",
    ) -> bool:
        payload: dict[str, Any] = {"chatId": chat_id, **image}
        if caption:
            payload["caption"] = caption[:1024]
        return await self._post_with_retry("/send-image", payload)

    async def send_to_phone(
        self,
        phone: str,
        text: str,
        mapper: UserMapper,
        image_url: str = "",
    ) -> bool:
        chat_id = mapper.e164_to_chat_id(phone)
        digits = chat_id.split("@")[0]
        exists = await self.check_number(digits)
        if exists is False:
            logger.warning("Phone not registered on WhatsApp: chat_id=%s", chat_id)
            return False

        text_ok = await self.send_text(chat_id, text)
        if not image_url.strip():
            return text_ok

        image_payload = await resolve_image_payload(image_url, self._settings)
        if not image_payload:
            logger.warning("Skipping image — could not resolve image_url")
            return text_ok

        image_ok = await self.send_image(chat_id, image_payload)
        if image_ok:
            logger.info("Image sent for chat_id=%s", chat_id.split("@")[0][:4] + "***")
        return text_ok and image_ok
