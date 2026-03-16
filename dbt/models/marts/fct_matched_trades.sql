{{
    config(
        materialized='table',
        sort=['matched_at'],
        cluster_by=['trade_date']
    )
}}

with matched as (
    select * from {{ ref('stg_matched_trades') }}
),

runs as (
    select
        run_id,
        trade_date,
        triggered_by
    from {{ ref('stg_recon_runs') }}
),

final as (
    select
        -- Match identity
        m.match_id,
        m.run_id,
        r.trade_date,

        -- Instruments
        m.trade_id,
        m.execution_id,
        m.instrument_type,

        -- Values
        m.notional_usd,
        m.qty_variance,
        m.price_variance_pct,

        -- Match quality
        m.match_confidence,
        m.is_exact_match,

        -- Run context
        r.triggered_by,

        -- Timing
        m.matched_at,

        -- Audit
        m._dbt_loaded_at

    from matched m
    left join runs r on m.run_id = r.run_id
)

select * from final
