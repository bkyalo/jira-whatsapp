import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def normalize_e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone.strip())
    if not digits:
        return ""
    return f"+{digits}"


class UserMapper:
    def __init__(self, map_path: Path) -> None:
        self._map_path = map_path
        self._email_to_phone: dict[str, str] = {}
        self._account_id_to_phone: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        if not self._map_path.exists():
            logger.warning("User map file not found: %s", self._map_path)
            self._email_to_phone = {}
            self._account_id_to_phone = {}
            return

        with self._map_path.open(encoding="utf-8") as f:
            raw = json.load(f)

        if "emails" in raw or "account_ids" in raw:
            emails = raw.get("emails") or {}
            account_ids = raw.get("account_ids") or {}
        else:
            emails = raw
            account_ids = {}

        self._email_to_phone = {
            email.strip().lower(): normalize_e164(phone)
            for email, phone in emails.items()
            if email and phone
        }
        self._account_id_to_phone = {
            account_id.strip(): normalize_e164(phone)
            for account_id, phone in account_ids.items()
            if account_id and phone
        }
        total = len(self._email_to_phone) + len(self._account_id_to_phone)
        logger.info(
            "Loaded %d mappings (%d emails, %d account IDs) from %s",
            total,
            len(self._email_to_phone),
            len(self._account_id_to_phone),
            self._map_path,
        )

    def lookup_email(self, email: str | None) -> str | None:
        if not email or not email.strip():
            return None
        return self._email_to_phone.get(email.strip().lower())

    def lookup_account_id(self, account_id: str | None) -> str | None:
        if not account_id or not account_id.strip():
            return None
        return self._account_id_to_phone.get(account_id.strip())

    def lookup(self, email: str | None = None, account_id: str | None = None) -> str | None:
        return self.lookup_email(email) or self.lookup_account_id(account_id)

    @staticmethod
    def e164_to_chat_id(phone: str) -> str:
        """Convert +254712345678 to 254712345678@c.us."""
        digits = re.sub(r"\D", "", phone)
        if not digits:
            raise ValueError(f"Invalid phone number: {phone!r}")
        return f"{digits}@c.us"
