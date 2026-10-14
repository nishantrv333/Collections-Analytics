/* Was each instalment paid?

   An instalment is kept when the money paid on the account, from the day the promise was
   made until 3 days after the due date, covers at least 95% of everything due on that
   promise up to and including this instalment.

   I use net_amount, so a payment that was later returned does not count. That means a
   returned direct debit reopens the instalment it had paid, even weeks later.
   An instalment is only judged once its grace period is over (is_matured). */
with schedule as (
    select
        i.promise_id,
        p.account_id,
        p.created_date,
        p.created_by,
        p.n_instalments,
        i.instalment_no,
        i.due_date,
        i.amount,
        sum(i.amount) over (partition by i.promise_id order by i.instalment_no) as cumulative_due
    from stg_promise_instalments i
    join stg_promises p using (promise_id)
),
paid as (
    select
        s.promise_id,
        s.instalment_no,
        coalesce(sum(pay.net_amount), 0) as paid_by_grace_end
    from schedule s
    left join int_payments pay
        on pay.account_id = s.account_id
       and pay.payment_type = 'payment'
       and pay.paid_date >= s.created_date
       and pay.paid_date <= s.due_date + 3
    group by 1, 2
)
select
    s.*,
    p.paid_by_grace_end,
    s.due_date + 3 <= r.as_of_date as is_matured,
    case
        when s.due_date + 3 <= r.as_of_date then p.paid_by_grace_end >= 0.95 * s.cumulative_due
    end as is_kept
from schedule s
join paid p using (promise_id, instalment_no)
cross join stg_run_date r
