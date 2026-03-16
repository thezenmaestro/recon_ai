with source as (
    select * from {{ source('results', 'matched_trades') }}
),

renamed as (
    select
        -- Keys
        match_id,
        run_id,
        trade_id,
        execution_id,

        -- Security
        instrument_type,

        -- Values
        coalesce(notional_usd, 0)                                  as notional_usd,
        coalesce(qty_variance, 0)                                  as qty_variance,
        coalesce(price_variance_pct, 0)                            as price_variance_pct,

        -- Match quality
        match_confidence,

        -- Derived: was this an exact key match or a composite attribute match?
        (match_confidence = 'EXACT')                               as is_exact_match,

        -- Timing
        matched_at,

        -- Audit
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
