/* severity: error
   Nothing is sent to a customer before the bank placed the account with us. */
select t.attempt_id, t.account_id, t.started_at_utc, a.placed_at_utc
from stg_contact_attempts t
join stg_accounts a using (account_id)
where t.started_at_utc < a.placed_at_utc
