/* One row per account a bank placed with us. Local dates use the bank's time zone,
   because "placed on 1 July" should mean 1 July in Madrid, not in UTC. */
select
    a.account_id,
    a.client_id,
    a.external_ref,
    a.product,
    a.dpd_at_placement,
    case
        when a.dpd_at_placement <= 30 then '0_30'
        when a.dpd_at_placement <= 60 then '31_60'
        else '61_90'
    end as dpd_bucket,
    cast(a.placed_at_utc as timestamp) as placed_at_utc,
    cast((cast(a.placed_at_utc as timestamp) at time zone 'UTC') at time zone c.timezone as date) as placed_date,
    cast(a.balance_at_placement as decimal(14, 2)) as balance_at_placement,
    a.currency,
    a.language,
    a.has_email
from raw_accounts a
join raw_clients c using (client_id)
