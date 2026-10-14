/* severity: warn
   Weekdays with no published rate. Usually a bank holiday. The daily rate table carries the
   last rate forward, but a long gap is worth a look. */
select currency, rate_date, dayname(rate_date) as weekday
from int_fx_daily
where not is_published_rate
  and dayofweek(rate_date) between 1 and 5
  and currency <> 'EUR'
