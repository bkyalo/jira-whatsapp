import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def mask_phone(phone: str) -> str:
    """Mask phone for logs, e.g. +254712345678 -> +2547***5678."""
    digits = phone.lstrip("+")
    if len(digits) <= 6:
        return "***"
    return f"+{digits[:4]}***{digits[-4:]}"
