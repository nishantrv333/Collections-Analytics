/* Raw payments exactly as loaded from the banks' daily files. Not deduplicated here on
   purpose, so the checks can still see when a bank sends the same file twice. */
select
    p.payment_id,
    p.client_id,
    p.account_id,
    p.bank_reference,
    p.payment_type,
    p.reverses_bank_reference,
    cast(p.amount as decimal(14, 2)) as amount,
    p.currency,
    p.method,
    cast(p.paid_at_utc as timestamp) as paid_at_utc,
    cast((cast(p.paid_at_utc as timestamp) at time zone 'UTC') at time zone c.timezone as date) as paid_date,
    p.source_file,
    cast(strptime(regexp_extract(p.source_file, '(\d{8})', 1), '%Y%m%d') as date) as file_date,
    cast(p.loaded_at_utc as timestamp) as loaded_at_utc
from raw_payments p
join raw_clients c using (client_id)
