/* severity: warn
   The same bank transaction arriving in more than one load. int_payments keeps only the
   first copy, so this is a warning, not a failure, but someone should tell the bank. */
with repeats as (
    select *
    from stg_payments
    qualify row_number() over (partition by bank_reference order by loaded_at_utc, payment_id) > 1
)
select source_file, min(loaded_at_utc) as loaded_again_at, count(*) as repeated_rows, sum(amount) as amount
from repeats
group by 1
