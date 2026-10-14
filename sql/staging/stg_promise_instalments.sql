select
    promise_id,
    instalment_no,
    cast(due_date as date) as due_date,
    cast(amount as decimal(14, 2)) as amount
from raw_promise_instalments
