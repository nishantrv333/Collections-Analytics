/* One row per real bank transaction, with a euro amount.

   Banks sometimes resend a file. When Meridia did on 14 August, every payment in it was
   loaded twice under new payment_ids. bank_reference is the bank's own id for the
   transaction, so I keep the first copy we loaded (docs/investigation_duplicate_payments.md).

   net_amount: a payment minus anything later reversed against it. I use this when the question
   is "did this payment really happen" (promise kept). For cash questions (billing, recovery
   by day N) I use amount, where the reversal is its own negative row on the day it happened. */
with deduped as (
    select *
    from stg_payments
    qualify row_number() over (partition by bank_reference order by loaded_at_utc, payment_id) = 1
),
reversed as (
    select reverses_bank_reference as bank_reference, sum(amount) as reversed_amount
    from deduped
    where payment_type = 'reversal'
    group by 1
)
select
    p.payment_id,
    p.client_id,
    p.account_id,
    p.bank_reference,
    p.payment_type,
    p.reverses_bank_reference,
    p.amount,
    case
        when p.payment_type = 'payment' then p.amount + coalesce(r.reversed_amount, 0)
        else 0
    end as net_amount,
    p.currency,
    p.method,
    p.paid_at_utc,
    p.paid_date,
    p.file_date,
    strftime(p.paid_date, '%Y-%m') as paid_month,
    strftime(p.file_date, '%Y-%m') as billing_month,
    dayofweek(p.paid_date) in (0, 6) as paid_on_weekend,
    fx.units_per_eur,
    round(cast(p.amount as double) / fx.units_per_eur, 2) as amount_eur,
    p.source_file,
    p.loaded_at_utc
from deduped p
left join reversed r using (bank_reference)
left join int_fx_daily fx
    on fx.currency = p.currency
   and fx.rate_date = p.paid_date
