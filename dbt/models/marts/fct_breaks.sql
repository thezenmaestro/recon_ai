{{
    config(
        materialized='table',
        sort=['created_at', 'severity'],
        cluster_by=['trade_date', 'severity']
    )
}}

with breaks as (
    select * from {{ ref('stg_breaks') }}
),

-- Join run context to get trade_date on each break
runs as (
    select
        run_id,
        trade_date,
        triggered_by,
        match_rate_pct,
        sla_met
    from {{ ref('stg_recon_runs') }}
),

-- Position impact (one row per break, left-joined as it may not exist yet)
position_impact as (
    select * from {{ ref('stg_position_impact') }}
),

final as (
    select
        -- Break identity
        b.break_id,
        b.run_id,
        r.trade_date,

        -- Security / counterparty
        b.isin,
        b.instrument_type,
        b.counterparty,
        b.direction,
        b.trade_id,
        b.execution_id,

        -- Classification
        b.break_type,
        b.severity,

        -- Quantities
        b.booked_quantity,
        b.executed_quantity,
        b.quantity_gap,

        -- Prices
        b.booked_price,
        b.executed_price,
        b.price_variance_pct,

        -- Exposure
        b.notional_at_risk_usd,

        -- Settlement
        b.booked_settlement_date,
        b.executed_settlement_date,

        -- AI enrichment
        b.ai_explanation,
        b.recommended_action,
        b.enrichment_source,
        b.confidence,
        b.needs_human_review,
        b.is_claude_enhanced,

        -- Position impact (from position_impact.py)
        p.impact_id,
        coalesce(p.net_position_change, 0)              as net_position_change,
        p.net_position_direction,
        coalesce(p.pnl_impact_usd, 0)                   as pnl_impact_usd,
        coalesce(p.settlement_cash_impact_usd, 0)        as settlement_cash_impact_usd,
        coalesce(p.securities_delivery_impact, 0)        as securities_delivery_impact,
        coalesce(p.delta_impact, 0)                      as delta_impact,
        coalesce(p.dv01_impact_usd, 0)                   as dv01_impact_usd,
        p.risk_metric_notes,
        coalesce(p.total_financial_exposure_usd, 0)      as total_financial_exposure_usd,
        p.last_known_price,
        p.price_source,

        -- Run context
        r.triggered_by,
        r.match_rate_pct,
        r.sla_met                                        as run_sla_met,

        -- Timing
        b.created_at,

        -- Audit
        b._dbt_loaded_at

    from breaks b
    left join runs r on b.run_id = r.run_id
    left join position_impact p on b.break_id = p.break_id
)

select * from final
