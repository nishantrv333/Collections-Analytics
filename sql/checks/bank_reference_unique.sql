/* severity: error
   After deduplication, one row per bank transaction. */
select bank_reference, count(*) as rows
from int_payments
group by 1
having count(*) > 1
