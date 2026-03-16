"""Email notifications via SMTP."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yaml

from src.notifications.retry import TransientError, retry_with_backoff

logger = logging.getLogger(__name__)

_ROUTING_PATH = os.path.join(os.path.dirname(__file__), "../../config/alert_routing.yaml")
with open(_ROUTING_PATH, encoding="utf-8") as _f:
    _ROUTING = yaml.safe_load(_f)

_EMAIL_FMT = _ROUTING.get("notification_formatting", {}).get("email", {})

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 2.0   # SMTP servers tolerate longer gaps than HTTP


def send_email(to: list[str], subject: str, body: str) -> None:
    """
    Send an email via SMTP.

    Environment variables required:
        SMTP_HOST       — SMTP server hostname (e.g. smtp.office365.com)
        SMTP_PORT       — SMTP port (e.g. 587 for STARTTLS)
        SMTP_USER       — SMTP login username
        SMTP_PASSWORD   — SMTP login password
        EMAIL_FROM      — Sender address (e.g. recon-system@yourfirm.com)

    Args:
        to: List of recipient email addresses.
        subject: Email subject line.
        body: Plain text email body.
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("EMAIL_FROM", smtp_user)

    if not smtp_host or not smtp_user:
        logger.warning("SMTP not configured; skipping alert to %s", to)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)

    # Plain text part
    msg.attach(MIMEText(body, "plain"))

    # HTML part — simple table format
    header_color = _EMAIL_FMT.get("header_color", "#c0392b")
    footer_text = _EMAIL_FMT.get(
        "footer_text",
        "This is an automated message from the Trade Reconciliation System.",
    )
    html_body = f"""
    <html><body>
    <h2 style="color:{header_color};">Reconciliation Alert</h2>
    <pre style="font-family:monospace;background:#f8f8f8;padding:12px;border-radius:4px;">
{body}
    </pre>
    <p style="color:#888;font-size:11px;">{footer_text}</p>
    </body></html>
    """
    msg.attach(MIMEText(html_body, "html"))

    raw_message = msg.as_string()

    def _send() -> None:
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, to, raw_message)
        except smtplib.SMTPServerDisconnected as exc:
            raise TransientError(f"SMTP server disconnected: {exc}") from exc
        except smtplib.SMTPConnectError as exc:
            raise TransientError(f"Could not connect to SMTP server: {exc}") from exc
        except smtplib.SMTPException as exc:
            # Authentication failures etc. are not retryable
            raise

    retry_with_backoff(
        _send,
        attempts=_RETRY_ATTEMPTS,
        base_delay=_RETRY_BASE_DELAY,
        label=f"Email alert to {to}",
    )
    logger.info("Email alert sent to %s", to)
