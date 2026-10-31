# src/ai/message_validator.py
"""Message validation: word limits (email 60-90, DM 15-30) and basic content checks.
Messages that fail are marked Invalid and are never sent; they are not silently
padded or truncated.
"""
import logging
import re
from typing import Any, Dict, List

from src.database.db import get_all_messages, get_connection

LOGGER = logging.getLogger(__name__)

EMAIL_RANGE = (60, 90)
DM_RANGE = (15, 30)
_PLACEHOLDER = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>")


def count_words(text: str) -> int:
    return len(text.split()) if text else 0


def validate_messages(email: str, dm: str, name: str = "") -> Dict[str, Any]:
    email_count, dm_count = count_words(email), count_words(dm)
    errors: List[str] = []
    if not EMAIL_RANGE[0] <= email_count <= EMAIL_RANGE[1]:
        errors.append(f"Email must contain {EMAIL_RANGE[0]}-{EMAIL_RANGE[1]} words (got {email_count})")
    if not DM_RANGE[0] <= dm_count <= DM_RANGE[1]:
        errors.append(f"Instagram DM must contain {DM_RANGE[0]}-{DM_RANGE[1]} words (got {dm_count})")
    for label, text in (("Email", email), ("DM", dm)):
        if _PLACEHOLDER.search(text or ""):
            errors.append(f"{label} contains an unfilled placeholder")
    if name and name.split()[0].lower() not in (email or "").lower():
        errors.append("Email does not address the creator by name")
    return {"valid": not errors, "email_word_count": email_count, "dm_word_count": dm_count,
            "errors": errors}


def validate_all_messages() -> Dict[str, int]:
    """Stage 6: re-validate every stored message and update its status."""
    messages = get_all_messages()
    valid = 0
    with get_connection() as conn:
        for m in messages:
            res = validate_messages(m["email_body"], m["instagram_dm"])
            valid += res["valid"]
            conn.execute(
                "UPDATE messages SET validation_status = ?, validation_errors = ?, "
                "email_word_count = ?, dm_word_count = ? WHERE message_id = ?",
                ("Valid" if res["valid"] else "Invalid", "; ".join(res["errors"]),
                 res["email_word_count"], res["dm_word_count"], m["message_id"]))
    LOGGER.info("Validation: %d messages, %d valid, %d invalid", len(messages), valid, len(messages) - valid)
    return {"total": len(messages), "valid": valid, "invalid": len(messages) - valid}
