/* severity: error
   Every bank's monthly collections, converted to euros and back, land on the local total
   straight from the bank files. It compares against the source on purpose: a join that drops
   rows also drops them from any total taken after it, so only the source shows the gap.
   This is the check that found the missing weekend payments. */
with source as (
    select client_id, strftime(paid_date, '%Y-%m') as paid_month, sum(amount) as local_total
    from (
        select *
        from stg_payments
        qualify row_number() over (partition by bank_reference order by loaded_at_utc, payment_id) = 1
    )
    group by 1, 2
),
converted as (
    select client_id, paid_month, sum(amount_eur * units_per_eur) as round_trip_total
    from int_payments
    group by 1, 2
)
select s.client_id, s.paid_month, s.local_total, round(c.round_trip_total, 2) as round_trip_total
from source s
left join converted c using (client_id, paid_month)
where c.round_trip_total is null
   or abs(s.local_total - c.round_trip_total) > 0.001 * abs(s.local_total)
