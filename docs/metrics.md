# How every number is defined

This is the one place each number in the project is defined. Next to each one is the SQL file that calculates it, and nothing else in the project calculates it a second way. If someone needs a number that is not here, it gets added here first, then built.

## Rules that apply to every number

**Dates are the bank's local date.** Everything is stored in UTC, but "placed on 1 July" or "paid in September" means the bank's own calendar. A payment at 23:30 on 31 August in Mexico City is an August payment, even though it is 1 September in UTC. Calling hours are checked in local time for the same reason.

**One bank transaction counts once.** Banks sometimes resend a payment file. Every transaction has the bank's own `bank_reference`, so I keep the first copy we loaded and drop the rest (`int_payments`). I do not deduplicate on account, amount and date, because a customer can pay two equal instalments on the same day and both are real.

**Reversals are handled two ways, on purpose.**
* Cash view: a reversal is a negative payment on the day the money went back. Used for money collected, recovery by day N, and billing. This answers "how much money did we have on that day".
* Payment view: a payment minus anything later reversed against it (`net_amount`). Used for promise kept. This answers "did the customer really pay". It means a returned direct debit reopens the instalment it paid, even weeks later, so kept rates for recent months can drop slightly as returns arrive.

**Euros.** Rates are published on business days only, so every calendar day takes the last rate published on or before it (`int_fx_daily`). Money collected in euros uses the rate on the payment date. Recovery rates use the rate on the placement date for both the balance and the payments, so a currency move can never show up as a change in recovery.

**Each market's own calendar.** Banks send no payment files on their public holidays and direct debits do not settle on them, so business days follow the real 2026 calendar for each market (England, UAE, Spain, Mexico). Nobody is called on a public holiday either.

**As of date.** Banks send each business day's file with the payments from the day before, so the newest data is complete up to the day before the latest file. Right now that is 29 September 2026 (`stg_run_date`).

**A number only shows once its window is complete.** Recovery within 60 days is empty for an account placed 40 days ago, not a low number. Young cohorts never look worse just because they are young.

## The KPIs

| Number | The question it answers | How it is calculated | Where |
|---|---|---|---|
| Accounts placed | How much work did the bank give us? | Accounts by local placement date | `kpi_client_month` |
| Reach rate | Of the accounts we got, how many customers did we actually speak to? | Accounts with at least one right party contact, divided by accounts placed | `fct_accounts.was_reached` |
| Reached per call | How often does a call reach the right person? | Calls ending in a right party contact, divided by all voice calls | `kpi_client_month.rpc_rate_per_call` |
| Calls to reach | How many calls does it take to reach someone? | Voice calls up to and including the first right party contact, averaged over reached accounts | `kpi_funnel` |
| Promise rate | When we reach the customer, how often do we agree a payment? | Right party calls ending in a promise to pay, divided by right party calls | `kpi_client_month.promise_rate` |
| Paid on the call | How often does the customer pay while still on the call? | Right party calls ending in a card payment on the call, divided by right party calls | `kpi_client_month.paid_on_call_rate` |
| First instalment kept | Are the promises real? | First instalments paid in time, divided by first instalments whose grace period is over. Paid in time means the money paid on the account from the day of the promise until 3 days after the due date covers at least 95% of what was due | `int_instalments`, `kpi_client_month.promise_kept_rate` |
| Recovery within N days | How much of the debt did we get back? | Money collected within N days of placement, net of reversals by then, divided by the balance at placement. N is 7, 14, 30, 60 or 90 | `fct_accounts`, `kpi_cohort_recovery` |
| Net collected | How much money came in this month? | Payments minus reversals, by local paid date | `kpi_client_month.net_collected` |
| Billing base | What do we charge the success fee on? | Payments minus reversals in the bank's files dated in the month | `billing_usage_month.net_collected` |
| Billable minutes | Voice usage for banks that pay per minute | Talk time per call, rounded up to the whole minute, then added up | `stg_contact_attempts.billable_minutes` |
| Messages delivered | Message usage for banks that pay per message | WhatsApp, SMS and email that did not fail | `billing_usage_month.messages_delivered` |

## Two numbers that sound the same and are not

"How much did we collect in September" has two honest answers.

Operations means money by the date the customer paid. Finance means money in the bank files dated in September, because that is what the bank can check against its own records and it never changes once sent. The files run a day behind the payments, more over a weekend or a bank holiday, so the two months do not line up:

| Bank | By paid date (operations) | By file date (billing) | Difference |
|---|---:|---:|---:|
| Northgate Bank (GBP) | 1,648,852.64 | 1,823,169.76 | 174,317.12 |
| Desert Finance (AED) | 6,255,156.73 | 6,738,383.95 | 483,227.22 |
| Banco Meridia (EUR) | 1,044,540.78 | 1,101,954.90 | 57,414.12 |
| Lumen Pay (MXN) | 4,697,551.33 | 4,900,334.69 | 202,783.36 |

Northgate shows how big this can get. 31 August 2026 was the UK's late summer bank holiday, so Northgate's first September file, dated 1 September, carried four days of payments from Friday 28 August to Monday 31 August: GBP 174,317.12. That is exactly the gap between Northgate's two Septembers.

Neither is wrong. They are two different questions, and the mistake is letting both be called "collected in September" in the same meeting. In this project the dashboard and the KPI tables use the paid date, and only invoicing uses the file date. Each is labelled.

## Choices I made, and why

**Promise rate is out of right party calls, not all calls.** Out of all calls, it mixes two things: how good the dialer is at reaching people and how good the agent is once it does. A change to calling times would then move the promise rate even if the conversation did not change at all.

**3 days of grace and 95% for "kept".** Direct debits and bank transfers can take a couple of business days to land, and a customer who pays 96% of an instalment has, for any practical purpose, kept it. Both are one number in `int_instalments.sql` and easy to change if the business sees it differently.

**Kept is judged on the first instalment of the first promise.** 325 of the 11,521 accounts with a promise (2.8%) got a second promise after breaking the first one. For those, a payment can count towards both promises because their windows overlap. It does not affect the first instalment number, which is the one the business looks at, so I left it and wrote it down here instead.
