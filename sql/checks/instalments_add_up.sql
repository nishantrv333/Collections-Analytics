/* severity: error
   A promise's instalments add up to the promised total. */
select p.promise_id, p.total_amount, sum(i.amount) as instalments_total
from stg_promises p
join stg_promise_instalments i using (promise_id)
group by 1, 2
having abs(sum(i.amount) - p.total_amount) > 0.01
