"""Slack notifications via Incoming Webhook."""
from __future__ import annotations

import json
import os

import requests


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
        print(f"[Slack] SLACK_WEBHOOK_URL not set. Skipping alert to {channel}.")
        return

    payload = {
        "text": message,
        "username": "Recon Bot",
        "icon_emoji": ":bar_chart:",
    }

    response = requests.post(
        webhook_url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    if response.status_code != 200:
        print(f"[Slack] Failed to send alert. Status: {response.status_code} | {response.text}")
    else:
        print(f"[Slack] Alert sent to {channel}.")
