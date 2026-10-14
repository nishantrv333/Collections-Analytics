select
    contract_id,
    client_id,
    cast(valid_from as date) as valid_from,
    cast(valid_to as date) as valid_to,
    contract_currency,
    invoice_currency,
    cast(success_fee_pct as double) as success_fee_pct,
    cast(tier_threshold as double) as tier_threshold,
    cast(success_fee_pct_above as double) as success_fee_pct_above,
    cast(fee_per_voice_minute as double) as fee_per_voice_minute,
    cast(fee_per_message as double) as fee_per_message,
    cast(platform_fee_monthly as double) as platform_fee_monthly,
    cast(monthly_minimum as double) as monthly_minimum
from raw_contracts
