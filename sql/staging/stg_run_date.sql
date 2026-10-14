/* The last day we have every payment for. Banks send a file each business day with the
   payments from the day(s) before, so the newest file only covers up to the previous day. */
select max(file_date) - 1 as as_of_date
from (
    select cast(strptime(regexp_extract(source_file, '(\d{8})', 1), '%Y%m%d') as date) as file_date
    from raw_payments
)
