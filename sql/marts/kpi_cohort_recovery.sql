/* Recovery curves: share of the placed balance collected within N days of placement,
   for each bank and placement month, plus all banks together in euros.
   A cohort's curve stops at the last day every account in it has fully lived through. */
with cohorts as (
    select
        client_id,
        placed_month,
        count(*) as accounts,
        sum(cast(balance_at_placement as double)) as balance,
        sum(balance_eur) as balance_eur,
        (select as_of_date from stg_run_date) - max(placed_date) + 1 as max_complete_day
    from fct_accounts
    group by 1, 2
),
flows as (
    select
        a.client_id,
        a.placed_month,
        cf.day_n,
        sum(cast(cf.net_amount as double)) as amount,
        sum(cast(cf.net_amount as double) / a.placement_units_per_eur) as amount_eur
    from int_account_cashflow cf
    join fct_accounts a using (account_id)
    where cf.day_n between 0 and 89
    group by 1, 2, 3
),
per_client as (
    select
        c.client_id,
        c.placed_month,
        d.day as days_since_placement,
        c.accounts,
        c.balance,
        sum(coalesce(f.amount, 0)) over w as collected
    from cohorts c
    cross join (select unnest(range(1, 91)) as day) d
    left join flows f
        on f.client_id = c.client_id
       and f.placed_month = c.placed_month
       and f.day_n = d.day - 1
    where d.day <= c.max_complete_day
    window w as (partition by c.client_id, c.placed_month order by d.day)
),
all_cohorts as (
    select
        placed_month,
        sum(accounts) as accounts,
        sum(balance_eur) as balance_eur,
        min(max_complete_day) as max_complete_day
    from cohorts
    group by 1
),
all_flows as (
    select placed_month, day_n, sum(amount_eur) as amount_eur
    from flows
    group by 1, 2
),
all_clients as (
    select
        'ALL' as client_id,
        c.placed_month,
        d.day as days_since_placement,
        c.accounts,
        c.balance_eur as balance,
        sum(coalesce(f.amount_eur, 0)) over w as collected
    from all_cohorts c
    cross join (select unnest(range(1, 91)) as day) d
    left join all_flows f
        on f.placed_month = c.placed_month
       and f.day_n = d.day - 1
    where d.day <= c.max_complete_day
    window w as (partition by c.placed_month order by d.day)
)
select *, round(collected / balance, 4) as recovery_rate
from (
    select * from per_client
    union all
    select * from all_clients
)
order by client_id, placed_month, days_since_placement
