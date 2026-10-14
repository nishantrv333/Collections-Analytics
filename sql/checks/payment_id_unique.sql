/* severity: error
   Every loaded payment row has its own id. */
select payment_id, count(*) as rows
from stg_payments
group by 1
having count(*) > 1
