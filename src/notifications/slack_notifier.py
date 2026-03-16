"""Slack notifications via Incoming Webhook."""
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

_SLACK_FMT = _ROUTING.get("notification_formatting", {}).get("slack", {})

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0


def send_slack(channel: str, message: str) -> None:
    """
    Post a message to a Slack channel via Incoming Webhook.

    Environment variables required:
        SLACK_WEBHOOK_URL — your Slack app incoming webhook URL

    Args:
        channel: Slack channel name (e.g. #recon-ops). Informational only
                 when using a single webhook — the webhook targets a fixed channel.
                 For per-channel webhooks, map channel → URL in alert_routing.yaml.
        message: Plain text or Slack mrkdwn message body.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set; skipping alert to %s", channel)
        return

    payload = {
        "text": message,
        "username": _SLACK_FMT.get("bot_name", "Recon Bot"),
        "icon_emoji": _SLACK_FMT.get("icon_emoji", ":bar_chart:"),
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
            raise TransientError(f"Network error posting to Slack: {exc}") from exc

        if response.status_code == 200:
            return
        if response.status_code in (429, 500, 502, 503, 504):
            raise TransientError(
                f"Slack returned retryable HTTP {response.status_code}: {response.text[:200]}"
            )
        # 4xx client errors won't succeed on retry — log and give up
        logger.error(
            "Slack alert to %s failed — HTTP %d: %s",
            channel, response.status_code, response.text[:200],
        )

    retry_with_backoff(
        _post,
        attempts=_RETRY_ATTEMPTS,
        base_delay=_RETRY_BASE_DELAY,
        label=f"Slack alert to {channel}",
    )
    logger.info("Slack alert sent to %s", channel)
