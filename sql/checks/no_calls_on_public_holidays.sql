/* severity: error
   No calls on a public holiday in the customer's market. */
select t.attempt_id, t.client_id, cast(t.started_at_local as date) as call_date, h.holiday_name
from stg_contact_attempts t
join stg_clients c using (client_id)
join stg_public_holidays h
    on h.country = c.holiday_country
   and h.region = c.holiday_region
   and h.holiday_date = cast(t.started_at_local as date)
where t.is_voice
