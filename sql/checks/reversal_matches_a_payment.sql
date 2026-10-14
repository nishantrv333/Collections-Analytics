/* severity: error
   A reversal points to a real payment on the same account and never returns more than was paid. */
select r.payment_id, r.reverses_bank_reference, r.amount, p.amount as original_amount
from int_payments r
left join int_payments p
    on p.bank_reference = r.reverses_bank_reference
   and p.account_id = r.account_id
   and p.payment_type = 'payment'
where r.payment_type = 'reversal'
  and (p.payment_id is null or -r.amount > p.amount)
