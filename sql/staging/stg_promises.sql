select
    p.promise_id,
    p.account_id,
    p.attempt_id,
    cast(p.created_at_utc as timestamp) as created_at_utc,
    cast((cast(p.created_at_utc as timestamp) at time zone 'UTC') at time zone c.timezone as date) as created_date,
    p.created_by,
    p.n_instalments,
    cast(p.total_amount as decimal(14, 2)) as total_amount
from raw_promises p
join raw_accounts a using (account_id)
join raw_clients c on c.client_id = a.client_id
