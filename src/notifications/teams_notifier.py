"""Microsoft Teams notifications via Incoming Webhook (Adaptive Card)."""
from __future__ import annotations

import json
import logging
import os

import requests
import yaml

from src.notifications.retry import TransientError, retry_with_backoff

logger = logging.getLogger(__name__)

_ROUTING_PATH = os.path.join(os.path.dirname(__file__), "../../config/alert_routing.yaml")
with open(_ROUTING_PATH) as _f:
    _ROUTING = yaml.safe_load(_f)

_TEAMS_FMT = _ROUTING.get("notification_formatting", {}).get("teams", {})

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0


def send_teams(webhook_url: str, message: str) -> None:
    """
    Post a message to a Microsoft Teams channel via Incoming Webhook.

    Args:
        webhook_url: Full Teams webhook URL from alert_routing.yaml
        message: Plain text message (will be rendered in a Teams card)
    """
    if not webhook_url or webhook_url.startswith("https://yourfirm"):
        logger.warning("Teams webhook URL not configured; skipping alert")
        return

    # Teams uses Adaptive Cards — format as a simple MessageCard
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": _TEAMS_FMT.get("theme_color", "C0392B"),
        "summary": "Reconciliation Alert",
        "sections": [{
            "activityTitle": _TEAMS_FMT.get("card_title", "**Trade Reconciliation Alert**"),
            "activitySubtitle": _TEAMS_FMT.get("card_subtitle", "Automated nightly run"),
            "text": message.replace("\n", "<br>"),
        }],
    }

    def _post() -> None:
        try:
            response = requests.post(
                webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise TransientError(f"Network error posting to Teams: {exc}") from exc

        if response.status_code in (200, 204):
            return
        if response.status_code in (429, 500, 502, 503, 504):
            raise TransientError(
                f"Teams returned retryable HTTP {response.status_code}: {response.text[:200]}"
            )
        logger.error(
            "Teams alert failed — HTTP %d: %s",
            response.status_code, response.text[:200],
        )

    retry_with_backoff(
        _post,
        attempts=_RETRY_ATTEMPTS,
        base_delay=_RETRY_BASE_DELAY,
        label="Teams alert",
    )
    logger.info("Teams alert sent")
