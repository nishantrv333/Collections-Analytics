/* ECB style: how many units of the currency one euro buys. Published on business days only. */
select
    cast(rate_date as date) as rate_date,
    currency,
    cast(units_per_eur as double) as units_per_eur
from raw_fx_rates
