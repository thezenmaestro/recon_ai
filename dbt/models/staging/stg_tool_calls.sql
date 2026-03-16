with source as (
    select * from {{ source('observability', 'tool_calls') }}
),

renamed as (
    select
        -- Keys
        tool_call_id,
        api_call_id,
        run_id,
        trade_date,

        -- Tool identity
        tool_name,

        -- Performance
        coalesce(duration_ms, 0)                                   as duration_ms,
        coalesce(status, 'UNKNOWN')                                as status,
        (status = 'SUCCESS')                                       as call_succeeded,

        -- Payload sizes
        coalesce(input_size_bytes, 0)                              as input_size_bytes,
        coalesce(output_size_bytes, 0)                             as output_size_bytes,

        -- Errors
        error_message,

        -- Timing
        called_at,

        -- Audit
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
