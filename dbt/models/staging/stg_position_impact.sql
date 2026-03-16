with source as (
    select * from {{ source('results', 'position_impact') }}
),

renamed as (
    select
        -- Keys
        impact_id,
        run_id,
        break_id,

        -- Security / counterparty
        isin,
        instrument_type,
        counterparty,

        -- Position impact
        coalesce(net_position_change, 0)                           as net_position_change,
        net_position_direction,

        -- P&L exposure
        coalesce(pnl_impact_usd, 0)                                as pnl_impact_usd,
        coalesce(settlement_cash_impact_usd, 0)                    as settlement_cash_impact_usd,
        coalesce(securities_delivery_impact, 0)                    as securities_delivery_impact,

        -- Risk metrics
        coalesce(delta_impact, 0)                                  as delta_impact,
        coalesce(dv01_impact_usd, 0)                               as dv01_impact_usd,
        risk_metric_notes,

        -- Valuation
        as_of_date,
        last_known_price,
        price_source,

        -- Derived: total financial exposure (P&L + funding)
        coalesce(pnl_impact_usd, 0) + coalesce(settlement_cash_impact_usd, 0)
                                                                   as total_financial_exposure_usd,

        -- Audit
        current_timestamp()                                        as _dbt_loaded_at

    from source
)

select * from renamed
