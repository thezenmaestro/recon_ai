{{
    config(
        materialized='table',
        sort=['trade_date'],
        cluster_by=['counterparty', 'instrument_type']
    )
}}

-- Historical break patterns aggregated over a trailing 90-day window.
-- Used by the pattern detection dashboard and can supplement Claude's
-- cross-break analysis with institutional memory Claude lacks per-run.
--
-- One row per (trade_date, counterparty, instrument_type, break_type) grain.
-- Trailing window metrics allow dashboards to show "is this getting worse?"

with breaks as (
    select
        b.break_id,
        b.run_id,
        r.trade_date,
        b.counterparty,
        b.instrument_type,
        b.isin,
        b.break_type,
        b.severity,
        b.notional_at_risk_usd,
        b.is_claude_enhanced,
        b.created_at
    from {{ ref('stg_breaks') }} b
    inner join {{ ref('stg_recon_runs') }} r on b.run_id = r.run_id
    -- Only look at completed runs so partial/failed runs don't skew trends
    where r.status = 'COMPLETED'
),

-- Daily grain first
daily_grain as (
    select
        trade_date,
        counterparty,
        instrument_type,
        break_type,
        severity,
        count(*)                                as break_count,
        sum(notional_at_risk_usd)               as total_notional_at_risk_usd,
        max(notional_at_risk_usd)               as max_notional_single_break_usd,
        count(distinct isin)                    as distinct_isins_affected,
        count_if(is_claude_enhanced)            as claude_enhanced_count

    from breaks
    group by 1, 2, 3, 4, 5
),

-- Add trailing-window aggregates using Snowflake window functions
with_trailing_windows as (
    select
        trade_date,
        counterparty,
        instrument_type,
        break_type,
        severity,
        break_count,
        total_notional_at_risk_usd,
        max_notional_single_break_usd,
        distinct_isins_affected,
        claude_enhanced_count,

        -- 7-day rolling count (how many times has this exact pattern appeared this week?)
        sum(break_count) over (
            partition by counterparty, instrument_type, break_type
            order by trade_date
            rows between 6 preceding and current row
        )                                       as break_count_7d,

        -- 30-day rolling count
        sum(break_count) over (
            partition by counterparty, instrument_type, break_type
            order by trade_date
            rows between 29 preceding and current row
        )                                       as break_count_30d,

        -- 90-day rolling count (main trend window)
        sum(break_count) over (
            partition by counterparty, instrument_type, break_type
            order by trade_date
            rows between 89 preceding and current row
        )                                       as break_count_90d,

        -- 90-day rolling notional
        sum(total_notional_at_risk_usd) over (
            partition by counterparty, instrument_type, break_type
            order by trade_date
            rows between 89 preceding and current row
        )                                       as notional_at_risk_90d_usd,

        -- Days since last break for this pattern (lag)
        datediff(
            'day',
            lag(trade_date) over (
                partition by counterparty, instrument_type, break_type
                order by trade_date
            ),
            trade_date
        )                                       as days_since_last_occurrence,

        -- First time this pattern was ever seen
        min(trade_date) over (
            partition by counterparty, instrument_type, break_type
        )                                       as first_seen_date,

        -- Most recent occurrence (= trade_date for latest rows)
        max(trade_date) over (
            partition by counterparty, instrument_type, break_type
        )                                       as last_seen_date

    from daily_grain
),

final as (
    select
        trade_date,
        counterparty,
        instrument_type,
        break_type,
        severity,
        break_count,
        total_notional_at_risk_usd,
        max_notional_single_break_usd,
        distinct_isins_affected,
        claude_enhanced_count,

        -- Trailing windows
        break_count_7d,
        break_count_30d,
        break_count_90d,
        notional_at_risk_90d_usd,
        days_since_last_occurrence,

        -- Recurrence classification (useful for dashboard filtering)
        case
            when break_count_30d >= 10 then 'CHRONIC'
            when break_count_30d >= 5  then 'RECURRING'
            when break_count_30d >= 2  then 'OCCASIONAL'
            else 'ISOLATED'
        end                                     as recurrence_label,

        -- First / last seen
        first_seen_date,
        last_seen_date,
        datediff('day', first_seen_date, last_seen_date) as pattern_lifespan_days,

        -- Audit
        current_timestamp()                     as _dbt_loaded_at

    from with_trailing_windows
)

select * from final
