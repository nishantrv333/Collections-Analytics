select
    p.*,
    a.dpd_bucket,
    a.placed_date,
    p.paid_date - a.placed_date as days_since_placement
from int_payments p
join stg_accounts a using (account_id)
