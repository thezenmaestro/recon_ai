with source as (
    select * from {{ source('observability', 'ai_api_calls') }}
),

renamed as (
    select
        -- Keys
        call_id,
        run_id,
        trade_date,

        -- Model info
        model,
        coalesce(triggered_by, 'unknown')                          as triggered_by,

        -- Purpose of this call (BREAK_ENRICHMENT or future purposes)
        coalesce(call_purpose, 'UNKNOWN')                          as call_purpose,

        -- Token usage
        coalesce(input_tokens, 0)                                  as input_tokens,
        coalesce(output_tokens, 0)                                 as output_tokens,
        coalesce(thinking_tokens, 0)                               as thinking_tokens,
        coalesce(total_tokens, 0)                                  as total_tokens,

        -- Cost
        coalesce(cost_usd, 0)                                      as cost_usd,

        -- Performance
        coalesce(latency_ms, 0)                                    as latency_ms,
        stop_reason,

        -- Thinking usage
        coalesce(had_thinking, false)                              as had_thinking,
        coalesce(tool_use_count, 0)                                as tool_use_count,

        -- Status
        error,
        (error is null)                                            as call_succeeded,

        -- Derived: cost per 1K tokens (for comparing efficiency across models)
        case
            when coalesce(total_tokens, 0) > 0
            then round(cost_usd / total_tokens * 1000, 6)
            else 0
        end                                                        as cost_per_1k_tokens,

        -- Timing
        called_at,
        date_trunc('hour', called_at)                              as called_at_hour,

        -- Audit
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
