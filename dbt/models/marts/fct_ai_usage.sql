{{
    config(
        materialized='table',
        sort=['trade_date'],
        cluster_by=['trade_date']
    )
}}

-- One row per run, with full AI usage breakdown.
-- Joins run outcomes so cost can be contextualised against recon results.

with api_calls as (
    select * from {{ ref('stg_ai_api_calls') }}
),

runs as (
    select
        run_id,
        trade_date,
        trade_month,
        triggered_by,
        status,
        total_breaks,
        high_breaks,
        total_break_notional_usd,
        sla_met,
        run_outcome,
        match_rate_pct
    from {{ ref('fct_recon_runs') }}
),

-- Aggregate API calls to run level
usage_per_run as (
    select
        run_id,
        trade_date,
        model,

        count(*)                            as api_call_count,
        count_if(call_succeeded)            as successful_calls,
        count_if(not call_succeeded)        as failed_calls,

        sum(input_tokens)                   as total_input_tokens,
        sum(output_tokens)                  as total_output_tokens,
        sum(thinking_tokens)                as total_thinking_tokens,
        sum(total_tokens)                   as total_tokens,

        sum(cost_usd)                       as total_cost_usd,
        avg(cost_usd)                       as avg_cost_per_call_usd,

        avg(latency_ms)                     as avg_latency_ms,
        max(latency_ms)                     as max_latency_ms,
        min(latency_ms)                     as min_latency_ms,

        count_if(had_thinking)              as calls_with_thinking,
        sum(thinking_tokens)                as thinking_tokens_total,

        count_if(call_purpose = 'BREAK_ENRICHMENT') as break_enrichment_calls,
        count_if(call_purpose = 'UNKNOWN')           as purpose_unknown_calls,

        max(called_at)                      as last_call_at

    from api_calls
    group by 1, 2, 3
),

final as (
    select
        -- Keys
        u.run_id,
        u.trade_date,
        r.trade_month,
        u.model,

        -- Run context
        r.triggered_by,
        r.status,
        r.run_outcome,
        r.sla_met,
        r.match_rate_pct,
        r.total_breaks,
        r.high_breaks,
        r.total_break_notional_usd,

        -- API call stats
        u.api_call_count,
        u.successful_calls,
        u.failed_calls,

        -- Token usage
        u.total_input_tokens,
        u.total_output_tokens,
        u.total_thinking_tokens,
        u.total_tokens,

        -- Cost
        u.total_cost_usd,
        u.avg_cost_per_call_usd,

        -- Derived: cost per break (0 when no breaks)
        case
            when coalesce(r.total_breaks, 0) > 0
            then round(u.total_cost_usd / r.total_breaks, 6)
            else 0
        end                                 as cost_per_break_usd,

        -- Derived: cost per HIGH break (the main value driver for Claude enrichment)
        case
            when coalesce(r.high_breaks, 0) > 0
            then round(u.total_cost_usd / r.high_breaks, 6)
            else 0
        end                                 as cost_per_high_break_usd,

        -- Derived: cost per $1M notional at risk
        case
            when coalesce(r.total_break_notional_usd, 0) > 0
            then round(u.total_cost_usd / r.total_break_notional_usd * 1_000_000, 4)
            else 0
        end                                 as cost_per_1m_notional_usd,

        -- Performance
        u.avg_latency_ms,
        u.max_latency_ms,
        u.min_latency_ms,

        -- Thinking usage
        u.calls_with_thinking,
        u.thinking_tokens_total,

        -- Purpose breakdown
        u.break_enrichment_calls,
        u.purpose_unknown_calls,

        -- Timing
        u.last_call_at

    from usage_per_run u
    left join runs r on u.run_id = r.run_id
)

select * from final
