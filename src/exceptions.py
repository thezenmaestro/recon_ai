"""
Domain exception hierarchy for the trade reconciliation pipeline.

Raising typed exceptions rather than bare Exception lets callers
distinguish failure modes and lets operators understand what broke
from the exception class name alone — without reading the message.

Hierarchy:
    ReconError                      — base for all pipeline errors
    ├── ConfigurationError          — bad or missing config (re-exported from config_validator)
    ├── DataLoadError               — Snowflake / SFTP read failure
    │   └── EmptyDatasetError       — query returned zero rows (may be legitimate)
    ├── DataQualityError            — data loaded but structurally invalid
    ├── MatchingError               — unexpected failure inside the matcher
    ├── BreakClassificationError    — unexpected failure inside the classifier
    ├── EnrichmentError             — Claude API call or response parsing failure
    ├── PositionImpactError         — position / P&L calculation failure
    ├── PersistenceError            — Snowflake write failure
    └── NotificationError           — alert dispatch failure (non-fatal by default)
"""
from __future__ import annotations


class ReconError(Exception):
    """Base class for all trade reconciliation pipeline errors."""


class ConfigurationError(ReconError):
    """Required configuration is missing or invalid.

    Also raised by src.config_validator.validate_all(); this class is a
    re-export so callers can catch it from one location.
    """


class DataLoadError(ReconError):
    """Failed to load data from Snowflake or SFTP."""


class EmptyDatasetError(DataLoadError):
    """Query or file returned zero records.

    This may be legitimate (e.g. a public holiday) but callers should
    log a warning and decide whether to abort or proceed.
    """


class DataQualityError(ReconError):
    """Data was loaded but contains structural problems.

    Examples:
      - A required column (trade_id, isin) is missing from the DataFrame.
      - All values in a mandatory field are null.
    """


class MatchingError(ReconError):
    """Unexpected failure inside the matching engine."""


class BreakClassificationError(ReconError):
    """Unexpected failure inside the break classifier."""


class EnrichmentError(ReconError):
    """Claude API call failed or returned an unparseable response.

    The pipeline will fall back to template-only explanations when this
    is raised from _enrich_with_claude().
    """


class PositionImpactError(ReconError):
    """Failure during position / P&L impact calculation."""


class PersistenceError(ReconError):
    """Failed to write results to Snowflake."""


class NotificationError(ReconError):
    """Alert dispatch failed.

    Treated as non-fatal by the pipeline — results are still in Snowflake
    even if notifications could not be delivered.
    """
