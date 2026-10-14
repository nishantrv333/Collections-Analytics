select
    invoice_number,
    client_id,
    billing_month,
    cast(billed_collected_base as decimal(14, 2)) as billed_collected_base,
    contract_currency,
    cast(issued_on as date) as issued_on
from raw_invoices_issued
