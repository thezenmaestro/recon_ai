"""
Alert Router — tiered notification dispatch based on break severity + asset class.
Reads routing rules from config/alert_routing.yaml.
"""
from __future__ import annotations

import json
import os
from typing import Any

import yaml

from src.notifications.email_notifier import send_email
from src.notifications.slack_notifier import send_slack
from src.notifications.teams_notifier import send_teams

_ROUTING_PATH = os.path.join(os.path.dirname(__file__), "../../config/alert_routing.yaml")
with open(_ROUTING_PATH) as f:
    ROUTING = yaml.safe_load(f)


# =============================================================================
# ALERT ROUTER
# =============================================================================

def route_alerts(breaks_json: str, run_id: str, trade_date: str) -> str:
    """
    Route break alerts to the correct channels based on severity + asset class.
    Respects digest_mode setting — sends one grouped message per channel per run.

    Args:
        breaks_json: JSON output from classify_breaks() (with AI explanations added)
        run_id: Current reconciliation run ID
        trade_date: Trade date in YYYY-MM-DD format

    Returns:
        JSON string with dispatch summary.
    """
    data = json.loads(breaks_json)
    breaks = data.get("breaks", [])
    settings = ROUTING.get("alert_settings", {})
    digest_mode = settings.get("digest_mode", True)
    include_ai = settings.get("include_ai_explanation", True)
    include_impact = settings.get("include_position_impact", True)
    max_breaks = settings.get("max_breaks_in_summary", 10)

    if not breaks:
        return json.dumps({"dispatched": 0, "message": "No breaks to alert"})

    # Group breaks by (instrument_type, severity) for routing matrix lookup
    dispatched = []

    if digest_mode:
        # Build one digest per unique channel, then send
        channel_messages: dict[str, list[dict]] = {}  # channel_key → list of breaks

        for brk in breaks:
            instrument = brk.get("instrument_type", "DEFAULT").upper()
            severity = brk.get("severity", "LOW").upper()

            routing = _get_routing(instrument, severity)

            for channel_key in _all_channel_keys(routing):
                channel_messages.setdefault(channel_key, []).append(brk)

        for channel_key, channel_breaks in channel_messages.items():
            channel_type, channel_name = channel_key.split(":", 1)
            top_breaks = sorted(
                channel_breaks, key=lambda b: b.get("notional_at_risk_usd", 0), reverse=True
            )[:max_breaks]

            message = _build_digest_message(top_breaks, run_id, trade_date,
                                            include_ai, include_impact)
            _dispatch(channel_type, channel_name, message, trade_date)
            dispatched.append({"channel_type": channel_type, "channel": channel_name,
                                "break_count": len(channel_breaks)})
    else:
        # One alert per break
        for brk in breaks:
            instrument = brk.get("instrument_type", "DEFAULT").upper()
            severity = brk.get("severity", "LOW").upper()
            routing = _get_routing(instrument, severity)
            message = _build_single_break_message(brk, run_id, trade_date,
                                                  include_ai, include_impact)
            for channel_key in _all_channel_keys(routing):
                channel_type, channel_name = channel_key.split(":", 1)
                _dispatch(channel_type, channel_name, message, trade_date)
                dispatched.append({"channel_type": channel_type, "channel": channel_name,
                                    "break_id": brk.get("break_id")})

    return json.dumps({"dispatched": len(dispatched), "channels": dispatched})


# =============================================================================
# HELPERS
# =============================================================================

def _get_routing(instrument_type: str, severity: str) -> dict:
    matrix = ROUTING.get("routing_matrix", {})
    instrument_routing = matrix.get(instrument_type, matrix.get("DEFAULT", {}))
    return instrument_routing.get(severity, {})


def _all_channel_keys(routing: dict) -> list[str]:
    keys = []
    channels_cfg = ROUTING.get("channels", {})

    for slack_alias in routing.get("slack", []):
        channel_id = channels_cfg["slack"]["channels"].get(slack_alias, slack_alias)
        keys.append(f"slack:{channel_id}")

    for email_group in routing.get("email", []):
        keys.append(f"email:{email_group}")

    for teams_alias in routing.get("teams", []):
        webhook = channels_cfg["teams"]["webhooks"].get(teams_alias, "")
        if webhook:
            keys.append(f"teams:{teams_alias}")

    return keys


def _dispatch(channel_type: str, channel_name: str, message: str, trade_date: str) -> None:
    channels_cfg = ROUTING.get("channels", {})

    if channel_type == "slack":
        send_slack(channel=channel_name, message=message)

    elif channel_type == "email":
        recipients_map = channels_cfg["email"]["recipients"]
        recipients = recipients_map.get(channel_name, [])
        if recipients:
            send_email(
                to=recipients,
                subject=f"[RECON ALERT] Trade Date {trade_date} — Breaks Detected",
                body=message,
            )

    elif channel_type == "teams":
        webhook = channels_cfg["teams"]["webhooks"].get(channel_name, "")
        if webhook:
            send_teams(webhook_url=webhook, message=message)


def _build_digest_message(breaks: list[dict], run_id: str, trade_date: str,
                           include_ai: bool, include_impact: bool) -> str:
    total_notional = sum(b.get("notional_at_risk_usd", 0) for b in breaks)
    high_count = sum(1 for b in breaks if b.get("severity") == "HIGH")

    lines = [
        f"*RECON ALERT — Trade Date: {trade_date}*",
        f"Run ID: {run_id}",
        f"Total Breaks: {len(breaks)} | High Severity: {high_count} | "
        f"Total Notional at Risk: ${total_notional:,.0f}",
        "---",
    ]

    for i, brk in enumerate(breaks, 1):
        lines.append(
            f"{i}. [{brk.get('severity')}] {brk.get('break_type')} | "
            f"Trade: {brk.get('trade_id') or 'N/A'} | "
            f"{brk.get('instrument_type')} | {brk.get('counterparty')} | "
            f"${brk.get('notional_at_risk_usd', 0):,.0f}"
        )
        if include_ai and brk.get("ai_explanation"):
            lines.append(f"   AI: {brk['ai_explanation']}")
        if include_ai and brk.get("recommended_action"):
            lines.append(f"   Action: {brk['recommended_action']}")

    return "\n".join(lines)


def _build_single_break_message(brk: dict, run_id: str, trade_date: str,
                                 include_ai: bool, include_impact: bool) -> str:
    lines = [
        f"*RECON BREAK — {brk.get('severity')} Severity*",
        f"Trade Date: {trade_date} | Run: {run_id}",
        f"Trade ID: {brk.get('trade_id') or 'N/A'} | Type: {brk.get('break_type')}",
        f"Instrument: {brk.get('instrument_type')} | ISIN: {brk.get('isin') or 'N/A'}",
        f"Counterparty: {brk.get('counterparty')}",
        f"Notional at Risk: ${brk.get('notional_at_risk_usd', 0):,.0f}",
    ]
    if include_ai and brk.get("ai_explanation"):
        lines += ["---", f"Explanation: {brk['ai_explanation']}"]
    if include_ai and brk.get("recommended_action"):
        lines.append(f"Recommended Action: {brk['recommended_action']}")

    return "\n".join(lines)
