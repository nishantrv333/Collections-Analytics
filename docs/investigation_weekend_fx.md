# Weekend payments were missing from every euro total

## What I saw

I was adding a check that converts every bank's collections to euros and back again, expecting it to land on the same local amount. It did for Banco Meridia and did not for any other bank. The euro totals were short, by a lot:

| Bank | Euros with the first version | Euros, fixed | Missing |
|---|---:|---:|---:|
| Northgate Bank (GBP) | 6,173,780.78 | 7,369,759.92 | 16.2% |
| Desert Finance (AED) | 4,912,091.72 | 5,747,362.55 | 14.5% |
| Banco Meridia (EUR) | 3,858,716.91 | 3,858,716.91 | 0% |
| Lumen Pay (MXN) | 713,491.48 | 942,251.85 | 24.3% |

June to September, all from `output/investigations/weekend_fx_impact.csv`. Across all four banks, EUR 2.26 million of EUR 17.92 million was missing, about 13%.

## Root cause

The first version joined each payment to the FX table on the payment date. The project uses the ECB's real reference rates, and the ECB only publishes Monday to Friday. People pay on Saturdays and Sundays, especially by card, so every weekend payment found no rate and the inner join dropped it without any error.

Meridia was fine only because it collects in euros and never needed a rate. Lumen was hit hardest because its customers pay by card and cash voucher, and close to a quarter of its payments land on a weekend. In the UK and the UAE, card payments on Saturdays and Sundays made up about a sixth of the money.

This would have caused real damage. Lumen's recovery in the all banks view would have looked about a quarter worse than it was, and the UK and UAE books about a sixth worse. Anyone comparing markets in euros would have drawn the wrong conclusions, and nothing on the dashboard would have looked broken.

## The fix, at the source

1. `int_fx_daily` builds a rate for every calendar day and every currency, carrying the last published rate forward over weekends and bank holidays. This is what finance teams normally do with ECB rates.
2. Payments join to that daily table with a left join, so a missing rate shows up as an empty value instead of a missing row.
3. A check, `every_payment_has_fx`, fails the run if any payment has no euro amount. It lists the payment, the currency and the weekday, so if it ever fires, the cause is obvious.
4. A check, `fx_rate_gaps`, warns about any weekday with no published rate, so a long gap gets noticed instead of quietly carried forward.
5. A check, `euro_totals_round_trip`, converts each bank's monthly euro total back to its own currency and compares it with the bank files. It compares against the source on purpose: a join that drops rows also drops them from every total taken after it.

## What I took from it

The query was not wrong in a way that throws an error. It returned a confident, plausible number that was 13% too low. That is the kind of mistake I most want checks for, because nobody looks twice at a number that looks normal. The checks that compare totals between layers (`payments_tie_out`, and the euro round trip that found this) catch this whole family of problems, not just this one.
