/* What each bank is billed on, per billing month.

   Success fees are charged on money in the bank's payment files dated in that month, net of
   reversals in those files. I bill on the file date, not the paid date, because files never
   change once sent: the bank can tick every line on our invoice against its own files, and a
   late payment never forces us to reopen a month we already invoiced.

   Usage (minutes, messages) is counted by the local date the call or message happened. */
with collected as (
    select
        client_id,
        billing_month,
        sum(amount) filter (where payment_type = 'payment') as gross_collected,
        -coalesce(sum(amount) filter (where payment_type = 'reversal'), 0) as reversed,
        sum(amount) as net_collected,
        count(*) filter (where payment_type = 'payment') as payments,
        count(distinct source_file) as bank_files
    from int_payments
    group by 1, 2
),
usage as (
    select
        client_id,
        strftime(started_at_local, '%Y-%m') as billing_month,
        count(*) filter (where is_voice) as calls,
        sum(billable_minutes) as billable_minutes,
        count(*) filter (where not is_voice and outcome <> 'failed') as messages_delivered
    from stg_contact_attempts
    group by 1, 2
)
select
    u.client_id,
    u.billing_month,
    cl.currency as contract_currency,
    coalesce(c.gross_collected, 0) as gross_collected,
    coalesce(c.reversed, 0) as reversed,
    coalesce(c.net_collected, 0) as net_collected,
    coalesce(c.payments, 0) as payments,
    coalesce(c.bank_files, 0) as bank_files,
    u.calls,
    u.billable_minutes,
    u.messages_delivered
from usage u
join stg_clients cl using (client_id)
left join collected c using (client_id, billing_month)
order by 1, 2
