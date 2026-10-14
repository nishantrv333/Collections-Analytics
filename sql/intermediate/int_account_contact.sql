with firsts as (
    select
        account_id,
        min(started_at_utc) filter (where is_right_party_contact) as first_rpc_at_utc
    from stg_contact_attempts
    group by 1
)
select
    t.account_id,
    count(*) filter (where t.is_voice) as voice_attempts,
    count(*) filter (where not t.is_voice) as messages_sent,
    count(*) filter (where t.is_right_party_contact) as right_party_contacts,
    count(*) filter (where t.is_voice and (f.first_rpc_at_utc is null or t.started_at_utc <= f.first_rpc_at_utc))
        as calls_to_first_rpc,
    min(t.started_at_utc) filter (where t.is_voice) as first_call_at_utc,
    f.first_rpc_at_utc,
    round(sum(t.talk_seconds) filter (where t.is_voice) / 60.0, 1) as talk_minutes,
    coalesce(bool_or(t.call_result = 'paid_on_call'), false) as paid_on_call,
    coalesce(bool_or(t.call_result = 'hardship'), false) as flagged_hardship,
    coalesce(bool_or(t.call_result = 'dispute'), false) as raised_dispute
from stg_contact_attempts t
join firsts f using (account_id)
group by t.account_id, f.first_rpc_at_utc
