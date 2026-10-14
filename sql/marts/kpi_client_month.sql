/* The monthly numbers per bank. Every ratio here is defined in docs/metrics.md, and this
   file is the only place they are calculated. Months are the bank's local calendar month. */
with placed as (
    select
        client_id,
        placed_month as month,
        count(*) as accounts_placed,
        sum(balance_at_placement) as balance_placed,
        sum(balance_eur) as balance_placed_eur
    from fct_accounts
    group by 1, 2
),
calls as (
    select
        client_id,
        strftime(started_at_local, '%Y-%m') as month,
        count(*) filter (where is_voice) as calls,
        count(*) filter (where is_right_party_contact) as right_party_calls,
        count(*) filter (where call_result = 'promise_to_pay') as promise_calls,
        count(*) filter (where call_result = 'paid_on_call') as paid_on_call_calls,
        count(*) filter (where not is_voice and outcome <> 'failed') as messages_delivered,
        sum(billable_minutes) as billable_minutes
    from stg_contact_attempts
    group by 1, 2
),
kept as (
    select
        a.client_id,
        strftime(i.due_date, '%Y-%m') as month,
        count(*) filter (where i.is_matured) as first_instalments_due,
        count(*) filter (where i.is_kept) as first_instalments_kept
    from int_instalments i
    join stg_accounts a using (account_id)
    where i.instalment_no = 1
    group by 1, 2
),
money as (
    select
        client_id,
        paid_month as month,
        sum(amount) filter (where payment_type = 'payment') as gross_collected,
        -coalesce(sum(amount) filter (where payment_type = 'reversal'), 0) as reversed,
        sum(amount) as net_collected,
        sum(amount_eur) as net_collected_eur,
        count(distinct account_id) filter (where payment_type = 'payment') as paying_accounts
    from int_payments
    group by 1, 2
),
months as (
    select client_id, month from placed
    union select client_id, month from calls
    union select client_id, month from money
)
select
    m.client_id,
    m.month,
    coalesce(pl.accounts_placed, 0) as accounts_placed,
    coalesce(pl.balance_placed, 0) as balance_placed,
    coalesce(pl.balance_placed_eur, 0) as balance_placed_eur,
    coalesce(c.calls, 0) as calls,
    coalesce(c.right_party_calls, 0) as right_party_calls,
    round(c.right_party_calls / nullif(c.calls, 0), 4) as rpc_rate_per_call,
    coalesce(c.promise_calls, 0) as promise_calls,
    round(c.promise_calls / nullif(c.right_party_calls, 0), 4) as promise_rate,
    round(c.paid_on_call_calls / nullif(c.right_party_calls, 0), 4) as paid_on_call_rate,
    coalesce(k.first_instalments_due, 0) as first_instalments_due,
    round(k.first_instalments_kept / nullif(k.first_instalments_due, 0), 4) as promise_kept_rate,
    coalesce(mo.gross_collected, 0) as gross_collected,
    coalesce(mo.reversed, 0) as reversed,
    coalesce(mo.net_collected, 0) as net_collected,
    coalesce(mo.net_collected_eur, 0) as net_collected_eur,
    coalesce(mo.paying_accounts, 0) as paying_accounts,
    coalesce(c.messages_delivered, 0) as messages_delivered,
    coalesce(c.billable_minutes, 0) as billable_minutes
from months m
left join placed pl using (client_id, month)
left join calls c using (client_id, month)
left join kept k using (client_id, month)
left join money mo using (client_id, month)
order by 1, 2
