"""Append incoming Jira webhook payloads to a file for debugging."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REDACT_QUERY_KEYS = frozenset({"secret", "webhook_secret"})


def _redact_query(query: dict[str, str]) -> dict[str, str]:
    return {
        key: ("***" if key in REDACT_QUERY_KEYS else value)
        for key, value in query.items()
    }


def _truncate(value: Any, max_len: int = 8000) -> Any:
    if isinstance(value, str) and len(value) > max_len:
        return value[: max_len - 3] + "..."
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(item, max_len) for item in value[:50]]
    return value


class WebhookPayloadLogger:
    def __init__(self, log_path: Path | None) -> None:
        self._path = log_path
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Webhook payload file log: %s", log_path)

    def write(
        self,
        *,
        raw_payload: dict[str, Any],
        normalized_payload: dict[str, Any],
        query_params: dict[str, str],
        client_ip: str | None,
        status: str,
        validation_errors: list[Any] | None = None,
    ) -> None:
        if not self._path:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "client_ip": client_ip,
            "query": _redact_query(query_params),
            "raw": _truncate(raw_payload),
            "normalized": _truncate(normalized_payload),
        }
        if validation_errors is not None:
            entry["validation_errors"] = validation_errors

        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str))
                f.write("\n")
        except OSError as exc:
            logger.error("Failed to write webhook payload log: %s", exc)
