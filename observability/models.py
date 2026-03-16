"""
Observability event models.
These are written to Snowflake OBSERVABILITY schema and consumed by
Sigma / Basedash for dashboards.

Four event streams:
  1. AI_API_CALLS     — every Claude API call (tokens, cost, latency)
  2. TOOL_CALLS       — every tool invocation Claude made
  3. RUN_EVENTS       — run-level lifecycle events (started, completed, failed)
  4. USER_ACTIVITY    — who triggered what, from where

No imports from src/ — this module is fully independent.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


# =============================================================================
# MODEL PRICING TABLE (USD per 1M tokens)
# Update when Anthropic changes pricing.
# =============================================================================
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6":   {"input": 5.00,  "output": 25.00},
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":  {"input": 1.00,  "output": 5.00},
}

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for an API call."""
    pricing = MODEL_PRICING.get(model, {"input": 5.00, "output": 25.00})
    return round(
        (input_tokens  / 1_000_000) * pricing["input"] +
        (output_tokens / 1_000_000) * pricing["output"],
        6,
    )


# =============================================================================
# 1. AI_API_CALLS — one row per Claude API call
# =============================================================================
class AIAPICallEvent(BaseModel):
    call_id:          str      = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id:           Optional[str] = None
    trade_date:       Optional[str] = None       # YYYY-MM-DD
    model:            str      = "claude-opus-4-6"
    input_tokens:     int      = 0
    output_tokens:    int      = 0
    thinking_tokens:  int      = 0               # tokens used in adaptive thinking
    total_tokens:     int      = 0
    cost_usd:         float    = 0.0
    latency_ms:       int      = 0               # wall-clock ms for the API call
    stop_reason:      Optional[str] = None       # end_turn | tool_use | max_tokens
    had_thinking:     bool     = False
    tool_use_count:   int      = 0               # number of tool_use blocks returned
    triggered_by:     str      = "airflow"       # airflow | manual | event
    call_purpose:     Optional[str] = None       # e.g. BREAK_ENRICHMENT — what this call was for
    called_at:        datetime = Field(default_factory=datetime.utcnow)
    error:            Optional[str] = None


# =============================================================================
# 2. TOOL_CALLS — one row per tool invocation by Claude
# =============================================================================
class ToolCallEvent(BaseModel):
    tool_call_id:     str      = Field(default_factory=lambda: str(uuid.uuid4()))
    api_call_id:      Optional[str] = None       # FK → AIAPICallEvent.call_id
    run_id:           Optional[str] = None
    trade_date:       Optional[str] = None
    tool_name:        str                        # e.g. tool_load_booked_trades
    called_at:        datetime = Field(default_factory=datetime.utcnow)
    duration_ms:      int      = 0
    status:           str      = "SUCCESS"       # SUCCESS | FAILURE
    input_size_bytes: int      = 0               # len of JSON input string
    output_size_bytes:int      = 0               # len of JSON output string
    error_message:    Optional[str] = None


# =============================================================================
# 3. RUN_EVENTS — lifecycle milestones for each reconciliation run
# =============================================================================
class RunEvent(BaseModel):
    event_id:                 str      = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id:                   str
    trade_date:               str                            # YYYY-MM-DD
    event_type:               str                            # STARTED | COMPLETED | FAILED
    triggered_by:             str      = "airflow"
    status:                   Optional[str] = None           # RUNNING | COMPLETED | FAILED
    # Populated on COMPLETED / FAILED
    total_trades:             Optional[int]   = None
    total_executions:         Optional[int]   = None
    matched_count:            Optional[int]   = None
    break_count:              Optional[int]   = None
    high_severity_count:      Optional[int]   = None
    total_notional_at_risk_usd: Optional[float] = None
    total_api_calls:          Optional[int]   = None
    total_tokens_used:        Optional[int]   = None
    total_cost_usd:           Optional[float] = None
    duration_seconds:         Optional[float] = None
    error_message:            Optional[str]   = None
    occurred_at:              datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# 4. NOTIFICATION_DELIVERIES — outcome of every alert dispatch attempt
# =============================================================================
class NotificationDeliveryEvent(BaseModel):
    delivery_id:    str      = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id:         Optional[str] = None
    trade_date:     Optional[str] = None       # YYYY-MM-DD
    channel_type:   str                        # slack | email | teams
    channel_name:   str                        # channel, email group, or teams alias
    break_count:    int      = 0               # number of breaks included in message
    status:         str      = "SUCCESS"       # SUCCESS | FAILURE | SKIPPED
    attempts:       int      = 1               # total attempts made (incl. retries)
    error_message:  Optional[str] = None
    sent_at:        datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# 5. USER_ACTIVITY — who did what, when, and from where
# =============================================================================
class UserActivityEvent(BaseModel):
    activity_id:  str      = Field(default_factory=lambda: str(uuid.uuid4()))
    user:         str      = "system"            # username, email, or 'airflow'
    action:       str                            # RUN_RECON | MANUAL_RERUN | SETUP_TABLES | etc.
    source:       str      = "airflow"           # airflow | cli | api | manual
    run_id:       Optional[str] = None
    trade_date:   Optional[str] = None
    details:      Optional[str] = None           # JSON string for extra context
    ip_address:   Optional[str] = None
    occurred_at:  datetime = Field(default_factory=datetime.utcnow)
