with source as (
    select * from {{ source('results', 'breaks') }}
),

renamed as (
    select
        -- Keys
        break_id,
        run_id,
        coalesce(trade_id, '')                                     as trade_id,
        coalesce(execution_id, '')                                 as execution_id,

        -- Security / counterparty
        isin,
        instrument_type,
        counterparty,
        direction,

        -- Break classification
        break_type,
        severity,

        -- Quantities
        coalesce(booked_quantity, 0)                               as booked_quantity,
        coalesce(executed_quantity, 0)                             as executed_quantity,
        coalesce(quantity_gap, 0)                                  as quantity_gap,

        -- Prices
        coalesce(booked_price, 0)                                  as booked_price,
        coalesce(executed_price, 0)                                as executed_price,
        coalesce(price_variance_pct, 0)                            as price_variance_pct,

        -- Exposure
        coalesce(notional_at_risk_usd, 0)                          as notional_at_risk_usd,

        -- Settlement
        booked_settlement_date,
        executed_settlement_date,

        -- AI enrichment
        ai_explanation,
        recommended_action,

        -- Enrichment source: CLAUDE_ENHANCED (HIGH breaks) or TEMPLATE_ONLY (all others)
        -- Falls back to TEMPLATE_ONLY for rows written before this field was added
        coalesce(enrichment_source, 'TEMPLATE_ONLY')               as enrichment_source,

        -- Confidence from AI/template
        coalesce(confidence, 'HIGH')                               as confidence,
        coalesce(needs_human_review, false)                        as needs_human_review,

        -- Derived: is this a HIGH-severity Claude-enhanced break?
        (severity = 'HIGH' and coalesce(enrichment_source, '') = 'CLAUDE_ENHANCED')
                                                                   as is_claude_enhanced,

        -- Audit
        created_at,
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
