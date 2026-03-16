with source as (
    select * from {{ source('observability', 'user_activity') }}
),

renamed as (
    select
        -- Keys
        activity_id,

        -- Who / what / where
        coalesce(user_name, 'system')                              as user_name,
        action,
        coalesce(source, 'unknown')                                as source,

        -- Run context
        run_id,
        trade_date,

        -- Extra context
        details,
        ip_address,

        -- Timing
        occurred_at,
        date_trunc('day', occurred_at)                             as occurred_date,

        -- Audit
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
