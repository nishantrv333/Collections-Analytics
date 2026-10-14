select
    t.attempt_id,
    t.account_id,
    a.client_id,
    t.channel,
    t.channel = 'voice' as is_voice,
    cast(t.started_at_utc as timestamp) as started_at_utc,
    (cast(t.started_at_utc as timestamp) at time zone 'UTC') at time zone c.timezone as started_at_local,
    t.outcome,
    t.outcome = 'right_party' as is_right_party_contact,
    t.call_result,
    t.talk_seconds,
    /* banks are billed per connected minute, rounded up per call */
    case when t.channel = 'voice' then ceil(t.talk_seconds / 60.0) else 0 end as billable_minutes,
    t.agent_version
from raw_contact_attempts t
join raw_accounts a using (account_id)
join raw_clients c on c.client_id = a.client_id
