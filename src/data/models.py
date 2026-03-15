"""
Data models for the Trade Reconciliation system.
These are plain dataclasses / Pydantic models — no AI dependency here.
All tool functions and the agent layer import from this module.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    FX = "FX"
    BOND = "BOND"
    DERIVATIVE = "DERIVATIVE"
    UNKNOWN = "UNKNOWN"


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class BreakType(str, Enum):
    UNEXECUTED = "UNEXECUTED"               # Trade booked, no execution found
    QTY_MISMATCH = "QTY_MISMATCH"           # Executed qty ≠ booked qty
    PRICE_MISMATCH = "PRICE_MISMATCH"       # Executed price outside tolerance
    SETTLEMENT_DATE_MISMATCH = "SETTLEMENT_DATE_MISMATCH"
    PARTIAL_EXECUTION = "PARTIAL_EXECUTION" # Some qty executed, gap remains
    NEEDS_REVIEW = "NEEDS_REVIEW"           # AI flagged uncertainty


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    BREAK = "BREAK"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# =============================================================================
# SOURCE MODELS
# =============================================================================

class BookedTrade(BaseModel):
    """Represents a trade record from the OMS (Source A)."""
    trade_id: str
    isin: Optional[str] = None
    ticker: Optional[str] = None
    instrument_type: InstrumentType = InstrumentType.UNKNOWN
    counterparty: str
    direction: Direction
    quantity: Decimal
    price: Decimal
    notional: Decimal
    currency: str = "USD"
    trade_date: date
    settlement_date: date
    status: str

    class Config:
        use_enum_values = True


class ExecutedTransaction(BaseModel):
    """Represents an execution confirm from the broker (Source B)."""
    execution_id: str
    trade_ref_id: Optional[str] = None     # May be null if broker doesn't echo back
    isin: Optional[str] = None
    ticker: Optional[str] = None
    instrument_type: InstrumentType = InstrumentType.UNKNOWN
    counterparty: str
    direction: Direction
    executed_quantity: Decimal
    executed_price: Decimal
    executed_notional: Decimal
    currency: str = "USD"
    execution_date: date
    settlement_date: date
    status: str

    class Config:
        use_enum_values = True


# =============================================================================
# RECONCILIATION RESULTS MODELS
# =============================================================================

class MatchedPair(BaseModel):
    """A successfully matched trade ↔ execution pair."""
    match_id: str
    run_id: str
    trade_id: str
    execution_id: str
    instrument_type: str
    notional_usd: Decimal
    qty_variance: Decimal = Decimal("0")
    price_variance_pct: Decimal = Decimal("0")
    match_confidence: str = "EXACT"     # EXACT | COMPOSITE | FUZZY
    matched_at: datetime = Field(default_factory=datetime.utcnow)


class BreakRecord(BaseModel):
    """A reconciliation break — a gap between booked and executed."""
    break_id: str
    run_id: str
    trade_id: str
    execution_id: Optional[str] = None   # None if completely unexecuted
    instrument_type: str
    counterparty: str
    isin: Optional[str] = None
    direction: str
    break_type: BreakType
    severity: Severity

    # Financials
    booked_quantity: Decimal
    executed_quantity: Decimal = Decimal("0")
    quantity_gap: Decimal = Decimal("0")
    booked_price: Decimal
    executed_price: Optional[Decimal] = None
    price_variance_pct: Optional[Decimal] = None
    notional_at_risk_usd: Decimal       # USD-equivalent notional of the break

    # Dates
    booked_settlement_date: date
    executed_settlement_date: Optional[date] = None

    # AI-generated content
    ai_explanation: Optional[str] = None
    recommended_action: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class PositionImpact(BaseModel):
    """Forward position and valuation impact of a break."""
    impact_id: str
    run_id: str
    break_id: str
    isin: Optional[str] = None
    instrument_type: str
    counterparty: str

    # Position
    net_position_change: Decimal            # Units impact
    net_position_direction: str             # LONG | SHORT | FLAT

    # Valuation
    pnl_impact_usd: Decimal                 # Mark-to-market P&L impact
    settlement_cash_impact_usd: Decimal     # Cash needed / freed
    securities_delivery_impact: Decimal     # Units to deliver / receive

    # Risk
    delta_impact: Optional[Decimal] = None
    dv01_impact_usd: Optional[Decimal] = None
    risk_metric_notes: Optional[str] = None

    as_of_date: date
    last_known_price: Optional[Decimal] = None
    price_source: Optional[str] = None


class ReconRun(BaseModel):
    """Metadata record for a single reconciliation run."""
    run_id: str
    trade_date: date
    run_timestamp: datetime = Field(default_factory=datetime.utcnow)
    triggered_by: str = "airflow"           # airflow | manual | event

    # Counts
    total_trades: int = 0
    total_executions: int = 0
    matched_count: int = 0
    break_count: int = 0
    needs_review_count: int = 0

    # Financials
    total_matched_notional_usd: Decimal = Decimal("0")
    total_break_notional_usd: Decimal = Decimal("0")

    # Status
    status: str = "RUNNING"                 # RUNNING | COMPLETED | FAILED
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
