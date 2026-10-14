/* Money in and out per account per day since placement (day 0 is the placement day).
   Cash view: a reversal is a negative amount on the day it happened. */
select
    p.account_id,
    p.paid_date - a.placed_date as day_n,
    sum(p.amount) as net_amount
from int_payments p
join stg_accounts a using (account_id)
group by 1, 2
