with source as (
    select * from {{ source('results', 'recon_runs') }}
),

renamed as (
    select
        -- Keys
        run_id,
        trade_date,

        -- Metadata
        triggered_by,
        status,
        run_timestamp                                               as started_at,
        completed_at,

        -- Counts
        total_trades,
        total_executions,
        matched_count,
        break_count,
        coalesce(needs_review_count, 0)                            as needs_review_count,

        -- Notional
        coalesce(total_matched_notional_usd, 0)                    as total_matched_notional_usd,
        coalesce(total_break_notional_usd, 0)                      as total_break_notional_usd,

        -- Errors
        error_message,

        -- Derived: run duration in minutes
        datediff(
            'second', run_timestamp, completed_at
        )                                                           as run_duration_seconds,

        -- Derived: did the run complete before the 08:00 ET SLA?
        -- completed_at is stored UTC; America/Toronto handles EST/EDT automatically
        case
            when status = 'COMPLETED'
                and hour(convert_timezone('UTC', 'America/Toronto', completed_at)) < {{ var('sla_deadline_hour_et') }}
            then true
            else false
        end                                                         as sla_met,

        -- Derived: match rate (safely handles zero-trade days)
        round(
            matched_count * 100.0 / nullif(total_trades, 0), 2
        )                                                           as match_rate_pct,

        -- Derived: calendar grain for trend analysis
        date_trunc('month', trade_date)                            as trade_month,
        dayofweek(trade_date)                                      as trade_day_of_week,  -- 0=Sun

        -- Audit
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
