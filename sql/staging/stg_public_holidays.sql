/* Real public holiday calendars for each market (England, UAE, Spain, Mexico).
   UAE Islamic holidays follow the moon, so the dates are the published estimates. */
select
    country,
    coalesce(region, '') as region,
    cast(holiday_date as date) as holiday_date,
    name as holiday_name
from raw_public_holidays
