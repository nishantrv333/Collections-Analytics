/* Where accounts drop out, for accounts placed June to August (so each one has had at
   least 30 days). Outcomes are to date. */
select
    client_id,
    dpd_bucket,
    count(*) as accounts_placed,
    count(*) filter (where voice_attempts > 0) as called,
    count(*) filter (where was_reached) as reached,
    count(*) filter (where promises_made > 0 or paid_on_call) as agreed_to_pay,
    count(*) filter (where collected_to_date > 0) as paid_something,
    count(*) filter (where is_fully_paid) as paid_in_full,
    round(avg(calls_to_first_rpc) filter (where was_reached), 2) as avg_calls_to_reach
from fct_accounts
where placed_date < date '2026-09-01'
group by grouping sets ((client_id, dpd_bucket), (client_id), ())
order by client_id nulls last, dpd_bucket nulls first
