/* severity: error
   Voice calls only inside each market's calling window, in the customer's local time:
   UAE 09:00 to 20:00 Monday to Friday (Central Bank consumer protection rules), UK 08:00 to
   21:00 and Spain and Mexico 09:00 to 21:00, Monday to Saturday, as our stated policy where
   the regulator only says "not at unreasonable times". Never on a Sunday.
   It has to use local time: in UTC a 10:00 call in Mexico City looks like a 16:00 call. */
select t.attempt_id, t.client_id, t.started_at_local, dayname(t.started_at_local) as weekday
from stg_contact_attempts t
join stg_clients c using (client_id)
where t.is_voice
  and (
        hour(t.started_at_local) < c.call_start_hour
     or hour(t.started_at_local) >= c.call_end_hour
     or dayofweek(t.started_at_local) = 0
     or (dayofweek(t.started_at_local) = 6 and not c.calls_on_saturday)
  )
