with source as (
    select * from {{ source('observability', 'run_events') }}
),

renamed as (
    select
        -- Keys
        event_id,
        run_id,
        trade_date,

        -- Event context
        event_type,
        triggered_by,
        coalesce(status, 'UNKNOWN')                                as status,

        -- Volume metrics (only populated on COMPLETED events)
        total_trades,
        total_executions,
        matched_count,
        break_count,
        high_severity_count,
        total_notional_at_risk_usd,

        -- AI usage (only populated on COMPLETED events)
        total_api_calls,
        total_tokens_used,
        total_cost_usd,

        -- Performance
        duration_seconds,

        -- Derived: duration in minutes (for readability)
        round(coalesce(duration_seconds, 0) / 60.0, 2)            as duration_minutes,

        -- Errors
        error_message,

        -- Timing
        occurred_at,

        -- Audit
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
