/* severity: error
   We never collect more than the account owed. */
select account_id, client_id, balance_at_placement, collected_to_date
from fct_accounts
where collected_to_date > balance_at_placement + 0.01
