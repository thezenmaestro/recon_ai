"""
Config validator — fail fast on startup if required configuration is missing
or if placeholder values from the template have not been replaced.

Call validate_all() from main.py and the Airflow DAG before running the
reconciliation pipeline. A clear ConfigurationError is raised so operators
know exactly what to fix before any Snowflake or API connections are opened.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"

# Environment variables that must be set for the pipeline to run
_REQUIRED_ENV_VARS = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_RESULTS_DATABASE",
    "ANTHROPIC_API_KEY",
]

# Keys that must exist in field_mappings.yaml
_REQUIRED_FIELD_MAPPING_KEYS = [
    ("trades", "columns", "trade_id"),
    ("trades", "columns", "isin"),
    ("trades", "columns", "counterparty"),
    ("trades", "columns", "quantity"),
    ("trades", "columns", "price"),
    ("trades", "columns", "settlement_date"),
    ("executions", "columns", "execution_id"),
    ("executions", "columns", "trade_ref_id"),
    ("executions", "columns", "executed_quantity"),
    ("executions", "columns", "executed_price"),
    ("executions", "columns", "settlement_date"),
    ("trades", "filters", "active_statuses"),
    ("executions", "filters", "active_statuses"),
]

# Keys that must exist in business_rules.yaml
_REQUIRED_BUSINESS_RULE_KEYS = [
    ("matching", "tolerances", "DEFAULT"),
    ("breaks", "severity_thresholds", "LOW"),
    ("breaks", "severity_thresholds", "MEDIUM"),
    ("breaks", "severity_thresholds", "HIGH"),
    ("position", "fx_rate_fallback"),
]


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""


def _nested_get(data: dict, *keys):
    """Walk a nested dict by key path; return the value or raise KeyError."""
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise KeyError(".".join(str(k) for k in keys))
        current = current[key]
    return current


def _check_env_vars() -> list[str]:
    missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
    return [f"Missing environment variable: {v}" for v in missing]


def _check_yaml_keys(data: dict, required_keys: list[tuple], source: str) -> list[str]:
    errors = []
    for key_path in required_keys:
        try:
            _nested_get(data, *key_path)
        except KeyError:
            errors.append(f"{source}: required key '{'.'.join(key_path)}' is missing")
    return errors


def _check_replace_markers(data: dict, source: str) -> list[str]:
    """Detect any value that still contains the '← REPLACE' template marker."""
    errors = []

    def _walk(obj, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")
        elif isinstance(obj, str) and "← REPLACE" in obj:
            errors.append(f"{source}: '{path}' still contains a placeholder value — fill it in before running")

    _walk(data, "")
    return errors


def _check_field_mappings() -> list[str]:
    path = _CONFIG_DIR / "field_mappings.yaml"
    if not path.exists():
        return [f"config/field_mappings.yaml not found at {path}"]
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"config/field_mappings.yaml is not valid YAML: {e}"]

    errors = _check_yaml_keys(data, _REQUIRED_FIELD_MAPPING_KEYS, "field_mappings.yaml")
    errors += _check_replace_markers(data, "field_mappings.yaml")

    # Validate that each required Snowflake source has at least a schema+table
    for source_key in ("trades", "executions"):
        source_cfg = data.get(source_key, {})
        mode = source_cfg.get("source", "snowflake")
        if mode == "snowflake":
            sf = source_cfg.get("snowflake", {})
            for field in ("schema", "table"):
                if not sf.get(field):
                    errors.append(
                        f"field_mappings.yaml: {source_key}.snowflake.{field} is required when source=snowflake"
                    )

    return errors


def _check_business_rules() -> list[str]:
    path = _CONFIG_DIR / "business_rules.yaml"
    if not path.exists():
        return [f"config/business_rules.yaml not found at {path}"]
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"config/business_rules.yaml is not valid YAML: {e}"]

    errors = _check_yaml_keys(data, _REQUIRED_BUSINESS_RULE_KEYS, "business_rules.yaml")

    # Validate DEFAULT tolerance has required sub-keys
    try:
        default_tol = _nested_get(data, "matching", "tolerances", "DEFAULT")
        for sub_key in ("price_pct", "qty_abs", "date_days"):
            if sub_key not in default_tol:
                errors.append(
                    f"business_rules.yaml: matching.tolerances.DEFAULT.{sub_key} is missing"
                )
    except KeyError:
        pass  # Already caught above

    # Validate severity thresholds have numeric max_notional
    try:
        low_thresh = _nested_get(data, "breaks", "severity_thresholds", "LOW")
        if not isinstance(low_thresh.get("max_notional"), (int, float)):
            errors.append("business_rules.yaml: breaks.severity_thresholds.LOW.max_notional must be a number")
        med_thresh = _nested_get(data, "breaks", "severity_thresholds", "MEDIUM")
        if not isinstance(med_thresh.get("max_notional"), (int, float)):
            errors.append("business_rules.yaml: breaks.severity_thresholds.MEDIUM.max_notional must be a number")
    except KeyError:
        pass  # Already caught above

    return errors


def _check_alert_routing() -> list[str]:
    path = _CONFIG_DIR / "alert_routing.yaml"
    if not path.exists():
        return [f"config/alert_routing.yaml not found at {path}"]
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"config/alert_routing.yaml is not valid YAML: {e}"]

    errors = []
    if "routing_matrix" not in data:
        errors.append("alert_routing.yaml: 'routing_matrix' key is missing")
    if "channels" not in data:
        errors.append("alert_routing.yaml: 'channels' key is missing")

    return errors


def _check_system_prompt() -> list[str]:
    path = _CONFIG_DIR / "system_prompt.md"
    if not path.exists():
        return [f"config/system_prompt.md not found at {path}"]
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return ["config/system_prompt.md is empty — add your domain knowledge before running"]
    return []


def validate_all() -> None:
    """
    Run all configuration checks. Raises ConfigurationError listing every
    problem found so operators can fix them all at once.

    Call this at application startup before opening any connections.
    """
    logger.info("Validating configuration...")
    errors: list[str] = []

    errors += _check_env_vars()
    errors += _check_field_mappings()
    errors += _check_business_rules()
    errors += _check_alert_routing()
    errors += _check_system_prompt()

    if errors:
        bullet_list = "\n".join(f"  • {e}" for e in errors)
        raise ConfigurationError(
            f"Configuration validation failed ({len(errors)} error(s)):\n{bullet_list}\n\n"
            "Fix all issues above before re-running the pipeline."
        )

    logger.info("Configuration valid — %d checks passed", (
        len(_REQUIRED_ENV_VARS) + len(_REQUIRED_FIELD_MAPPING_KEYS) + len(_REQUIRED_BUSINESS_RULE_KEYS)
    ))
