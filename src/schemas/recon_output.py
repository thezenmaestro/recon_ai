"""
Pydantic schemas for Claude's structured outputs.
Claude uses these to produce consistent, parseable reconciliation results.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class BreakExplanation(BaseModel):
    """Claude's analysis of a single break."""
    break_id: str
    ai_explanation: str         # Plain English explanation for the ops team
    recommended_action: str     # Specific next step (e.g. "Contact counterparty X for confirmation")
    confidence: str             # HIGH | MEDIUM | LOW — how confident Claude is in the classification
    needs_human_review: bool    # True if Claude is uncertain


class ClaudeEnrichmentResponse(BaseModel):
    """
    Structured response from the single Claude enrichment call.
    Claude enhances HIGH-severity break explanations and produces the run narrative.
    LOW and MEDIUM breaks are handled locally by break_enricher.py.
    """
    break_explanations: List[BreakExplanation]  # Enhanced explanations for HIGH breaks only
    narrative: str                              # 2-3 sentence executive summary
    key_themes: List[str]                       # Cross-break patterns Claude observed
    immediate_actions: List[str]                # Ordered ops action list


class ReconSummary(BaseModel):
    """Claude's narrative summary of the entire reconciliation run."""
    run_id: str
    trade_date: str
    overall_status: str                         # CLEAN | BREAKS_FOUND | CRITICAL
    total_breaks: int
    high_severity_count: int
    total_notional_at_risk_usd: float
    narrative: str                              # Human-readable paragraph summary
    key_themes: List[str]                       # Recurring patterns, e.g. ["FX settlement lag", "Partial fills in AAPL"]
    immediate_actions: List[str]                # Ordered list of things ops must do NOW
    break_explanations: List[BreakExplanation]
