/* severity: error
   Every payment converts to euros. A payment without a rate silently disappears from any
   euro total, which is exactly what happened to weekend payments before I fixed the join. */
select payment_id, client_id, currency, paid_date, dayname(paid_date) as weekday
from int_payments
where amount_eur is null
