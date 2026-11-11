import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("tectha.email")


def send_email(to: str, subject: str, body: str) -> bool:
    """Send via SMTP when configured. Without SMTP, development logs the message; production logs a warning only."""
    if not settings.SMTP_HOST:
        if settings.is_production:
            log.warning("SMTP not configured; could not send '%s' to a user.", subject)
        else:
            log.warning("SMTP not configured (dev). Email to %s — %s\n%s", to, subject, body)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_STARTTLS:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException):
        log.exception("Failed to send email '%s'", subject)
        return False
