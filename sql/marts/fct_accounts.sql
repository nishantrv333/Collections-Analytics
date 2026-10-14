/* One row per account, with everything I usually need to answer a question about it.

   Recovery "within N days" counts money paid before placed_date + N and not reversed by then.
   It stays null until the account has had all N days, so a young cohort never looks worse
   than it is just because it is young.

   Euro amounts use the rate on the placement date for both the balance and the payments.
   That way a currency move can never show up as a change in recovery. */
with cash as (
    select
        account_id,
        sum(net_amount) as collected_to_date,
        coalesce(sum(net_amount) filter (where day_n < 7), 0) as c7,
        coalesce(sum(net_amount) filter (where day_n < 14), 0) as c14,
        coalesce(sum(net_amount) filter (where day_n < 30), 0) as c30,
        coalesce(sum(net_amount) filter (where day_n < 60), 0) as c60,
        coalesce(sum(net_amount) filter (where day_n < 90), 0) as c90
    from int_account_cashflow
    group by 1
),
promises as (
    select
        account_id,
        count(*) as promises_made,
        min(created_at_utc) as first_promise_at_utc,
        arg_min(promise_id, created_at_utc) as first_promise_id
    from stg_promises
    group by 1
),
first_instalment as (
    select promise_id, is_matured, is_kept
    from int_instalments
    where instalment_no = 1
)
select
    a.account_id,
    a.client_id,
    c.client_name,
    a.product,
    a.dpd_at_placement,
    a.dpd_bucket,
    a.placed_at_utc,
    a.placed_date,
    strftime(a.placed_date, '%Y-%m') as placed_month,
    a.language,
    a.currency,
    a.balance_at_placement,
    fx.units_per_eur as placement_units_per_eur,
    round(cast(a.balance_at_placement as double) / fx.units_per_eur, 2) as balance_eur,
    e.variant as experiment_variant,

    coalesce(ct.voice_attempts, 0) as voice_attempts,
    coalesce(ct.messages_sent, 0) as messages_sent,
    coalesce(ct.right_party_contacts, 0) as right_party_contacts,
    coalesce(ct.right_party_contacts, 0) > 0 as was_reached,
    ct.calls_to_first_rpc,
    ct.first_rpc_at_utc,
    coalesce(ct.talk_minutes, 0) as talk_minutes,
    coalesce(ct.paid_on_call, false) as paid_on_call,
    coalesce(ct.flagged_hardship, false) as flagged_hardship,
    coalesce(ct.raised_dispute, false) as raised_dispute,

    coalesce(p.promises_made, 0) as promises_made,
    p.first_promise_at_utc,
    fi.is_matured as first_instalment_matured,
    fi.is_kept as first_instalment_kept,

    coalesce(cash.collected_to_date, 0) as collected_to_date,
    coalesce(cash.collected_to_date, 0) >= 0.99 * a.balance_at_placement as is_fully_paid,
    case when a.placed_date + 6 <= r.as_of_date then coalesce(cash.c7, 0) end as collected_d7,
    case when a.placed_date + 13 <= r.as_of_date then coalesce(cash.c14, 0) end as collected_d14,
    case when a.placed_date + 29 <= r.as_of_date then coalesce(cash.c30, 0) end as collected_d30,
    case when a.placed_date + 59 <= r.as_of_date then coalesce(cash.c60, 0) end as collected_d60,
    case when a.placed_date + 89 <= r.as_of_date then coalesce(cash.c90, 0) end as collected_d90
from stg_accounts a
join stg_clients c using (client_id)
cross join stg_run_date r
left join int_fx_daily fx on fx.currency = a.currency and fx.rate_date = a.placed_date
left join stg_experiment_assignments e using (account_id)
left join int_account_contact ct using (account_id)
left join promises p using (account_id)
left join first_instalment fi on fi.promise_id = p.first_promise_id
left join cash using (account_id)
