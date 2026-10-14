/* severity: error
   Each account is in one variant, and every call it got used that variant's agent version. */
select e.account_id, e.variant, t.agent_version, count(*) as calls
from stg_experiment_assignments e
join stg_contact_attempts t using (account_id)
where t.is_voice
  and t.agent_version <> case e.variant when 'treatment' then 'v4.3' else 'v4.2' end
group by 1, 2, 3
