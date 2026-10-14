select
    client_id,
    name as client_name,
    country,
    currency,
    timezone,
    product,
    cast(go_live as date) as go_live_date,
    call_start_hour,
    call_end_hour,
    calls_on_saturday,
    holiday_country,
    coalesce(holiday_region, '') as holiday_region
from raw_clients
