{{
    config(
        materialized='table',
        sort=['trade_date', 'started_at'],
        cluster_by=['trade_date']
    )
}}

with runs as (
    select * from {{ ref('stg_recon_runs') }}
),

-- Roll up AI cost per run from individual API call records
ai_cost_per_run as (
    select
        run_id,
        sum(cost_usd)       as ai_cost_usd,
        sum(total_tokens)   as total_tokens_used,
        count(*)            as api_call_count,
        sum(input_tokens)   as total_input_tokens,
        sum(output_tokens)  as total_output_tokens,
        sum(thinking_tokens)as total_thinking_tokens,
        avg(latency_ms)     as avg_api_latency_ms,
        max(latency_ms)     as max_api_latency_ms,
        count_if(call_purpose = 'BREAK_ENRICHMENT') as enrichment_calls,
        count_if(not call_succeeded)                as failed_api_calls
    from {{ ref('stg_ai_api_calls') }}
    group by 1
),

-- Break summary per run
break_summary_per_run as (
    select
        run_id,
        count(*)                                                as total_breaks,
        count_if(severity = 'HIGH')                             as high_breaks,
        count_if(severity = 'MEDIUM')                           as medium_breaks,
        count_if(severity = 'LOW')                              as low_breaks,
        count_if(is_claude_enhanced)                            as claude_enhanced_breaks,
        count_if(needs_human_review)                            as needs_review_count,
        sum(notional_at_risk_usd)                               as total_break_notional_usd,
        max(notional_at_risk_usd)                               as largest_break_usd,
        count(distinct counterparty)                            as distinct_counterparties_with_breaks,
        count(distinct instrument_type)                         as distinct_instrument_types_with_breaks
    from {{ ref('stg_breaks') }}
    group by 1
),

final as (
    select
        -- Run identity
        r.run_id,
        r.trade_date,
        r.trade_month,
        r.trade_day_of_week,
        r.triggered_by,
        r.status,

        -- Timing
        r.started_at,
        r.completed_at,
        r.run_duration_seconds,
        round(r.run_duration_seconds / 60.0, 2)                as run_duration_minutes,

        -- SLA
        r.sla_met,
        case
            when r.sla_met then 'ON_TIME'
            when r.status = 'FAILED' then 'FAILED'
            when r.status = 'RUNNING' then 'IN_PROGRESS'
            else 'LATE'
        end                                                     as sla_status,

        -- Volume
        coalesce(r.total_trades, 0)                             as total_trades,
        coalesce(r.total_executions, 0)                         as total_executions,
        coalesce(r.matched_count, 0)                            as matched_count,
        r.match_rate_pct,

        -- Breaks
        coalesce(b.total_breaks, 0)                             as total_breaks,
        coalesce(b.high_breaks, 0)                              as high_breaks,
        coalesce(b.medium_breaks, 0)                            as medium_breaks,
        coalesce(b.low_breaks, 0)                               as low_breaks,
        coalesce(b.claude_enhanced_breaks, 0)                   as claude_enhanced_breaks,
        coalesce(b.needs_review_count, 0)                       as needs_review_count,
        coalesce(b.total_break_notional_usd, 0)                 as total_break_notional_usd,
        coalesce(b.largest_break_usd, 0)                        as largest_break_usd,
        coalesce(b.distinct_counterparties_with_breaks, 0)      as distinct_counterparties_with_breaks,
        coalesce(b.distinct_instrument_types_with_breaks, 0)    as distinct_instrument_types_with_breaks,

        -- Overall status classification
        case
            when r.status = 'FAILED' then 'FAILED'
            when coalesce(b.total_breaks, 0) = 0 then 'CLEAN'
            when coalesce(b.high_breaks, 0) > 0 then 'CRITICAL'
            else 'BREAKS_FOUND'
        end                                                     as run_outcome,

        -- AI cost attribution
        coalesce(c.ai_cost_usd, 0)                              as ai_cost_usd,
        coalesce(c.total_tokens_used, 0)                        as total_tokens_used,
        coalesce(c.total_input_tokens, 0)                       as total_input_tokens,
        coalesce(c.total_output_tokens, 0)                      as total_output_tokens,
        coalesce(c.total_thinking_tokens, 0)                    as total_thinking_tokens,
        coalesce(c.api_call_count, 0)                           as api_call_count,
        coalesce(c.enrichment_calls, 0)                         as enrichment_calls,
        coalesce(c.failed_api_calls, 0)                         as failed_api_calls,
        coalesce(c.avg_api_latency_ms, 0)                       as avg_api_latency_ms,
        coalesce(c.max_api_latency_ms, 0)                       as max_api_latency_ms,

        -- Derived: AI cost per break (meaningful when breaks exist)
        case
            when coalesce(b.total_breaks, 0) > 0
            then round(coalesce(c.ai_cost_usd, 0) / b.total_breaks, 6)
            else 0
        end                                                     as ai_cost_per_break_usd,

        -- Error info
        r.error_message,

        -- Audit
        r._dbt_loaded_at

    from runs r
    left join break_summary_per_run b on r.run_id = b.run_id
    left join ai_cost_per_run c on r.run_id = c.run_id
)

select * from final
