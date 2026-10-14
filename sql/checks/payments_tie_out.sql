/* severity: error
   The marts do not lose or invent money: collected per bank per month in the KPI table equals
   the deduplicated payments. */
with source as (
    select client_id, paid_month as month, sum(amount) as amount
    from int_payments
    group by 1, 2
)
select s.client_id, s.month, s.amount as source_amount, k.net_collected as kpi_amount
from source s
full join kpi_client_month k using (client_id, month)
where coalesce(s.amount, 0) <> coalesce(k.net_collected, 0)
