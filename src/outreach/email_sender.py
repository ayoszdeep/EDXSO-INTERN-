# src/outreach/email_sender.py
"""Email delivery: 'simulation' (default, nothing leaves the machine) or 'real' (SMTP).
Real mode needs SMTP_USER / SMTP_PASSWORD (for Gmail: an App Password).
Set TEST_RECIPIENT_OVERRIDE to route every real email to your own inbox for demos.
"""
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, Optional

from config.settings import settings

LOGGER = logging.getLogger(__name__)


def _result(status: str, notes: Optional[str] = None) -> Dict[str, Any]:
    return {"status": status, "sent_at": datetime.now(timezone.utc).isoformat(), "notes": notes}


def build_email(to_email: str, subject: str, body: str, signature: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(f"{body}\n\n{signature}".strip())
    return msg


def send_email(to_email: str, subject: str, body: str, mode: str = "simulation",
               signature: str = "") -> Dict[str, Any]:
    """Returns {'status': Simulated|Sent|Skipped|Failed, 'sent_at', 'notes'}."""
    if not to_email or to_email.strip().lower() in ("not found", "none", "null", ""):
        return _result("Skipped", "Recipient email unavailable ('Not Found')")

    if mode == "simulation":
        LOGGER.info("[SIMULATION] Email to %s | %s", to_email, subject)
        return _result("Simulated", "Simulation mode: email not actually sent")

    if mode != "real":
        return _result("Failed", f"Unknown sending mode '{mode}'")

    if not (settings.SMTP_USER and settings.SMTP_PASSWORD):
        return _result("Failed", "Real mode requires SMTP_USER and SMTP_PASSWORD in .env")

    recipient = settings.TEST_RECIPIENT_OVERRIDE or to_email
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(build_email(recipient, subject, body, signature))
    except (smtplib.SMTPException, OSError) as e:
        LOGGER.error("Email to %s failed: %s", recipient, e)
        return _result("Failed", str(e)[:300])

    note = f"Sent to test inbox {recipient} instead of {to_email}" if recipient != to_email else None
    LOGGER.info("[REAL] Email sent to %s | %s", recipient, subject)
    return _result("Sent", note)
