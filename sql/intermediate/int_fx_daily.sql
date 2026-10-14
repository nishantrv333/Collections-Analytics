/* Rates are only published on business days, but people pay on Saturdays and Sundays too.
   For every calendar day I take the last rate published on or before that day. */
with bounds as (
    select
        min(rate_date) as first_day,
        greatest(max(rate_date), (select max(paid_date) from stg_payments)) as last_day
    from stg_fx_rates
),
days as (
    select cast(unnest(generate_series(first_day, last_day, interval 1 day)) as date) as rate_date
    from bounds
),
grid as (
    select d.rate_date, c.currency
    from days d
    cross join (select distinct currency from stg_fx_rates) c
)
select
    g.rate_date,
    g.currency,
    last_value(f.units_per_eur ignore nulls) over (
        partition by g.currency order by g.rate_date
        rows between unbounded preceding and current row
    ) as units_per_eur,
    f.units_per_eur is not null as is_published_rate
from grid g
left join stg_fx_rates f using (rate_date, currency)

union all

select rate_date, 'EUR', 1.0, true
from days
