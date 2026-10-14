# Meridia's August looked 4.7% better than it was

## What I saw

When I put the monthly numbers next to each other, Banco Meridia's August collections were a bit higher than I expected from the July and September trend. Not dramatically, which is why it would have been easy to miss.

So I looked at Meridia's payments day by day through August (`output/investigations/meridia_daily_payments_august.csv`). One day stood out:

| Paid date | Money as loaded | Payment rows | Accounts paying | Rows per account |
|---|---:|---:|---:|---:|
| Wed 12 Aug | 31,839.50 | 47 | 47 | 1.00 |
| Thu 13 Aug | 103,407.76 | 94 | 47 | 2.00 |
| Fri 14 Aug | 39,674.58 | 56 | 56 | 1.00 |

On 13 August the money doubled but the number of people paying did not. Exactly two rows per account is not customer behaviour, it is the same data twice.

## Root cause

Every one of those rows came from `meridia_payments_20260814.csv`. The file was loaded at 03:00 on 14 August, then loaded again at 03:12 on 15 August. Meridia's upload had timed out and their system sent the file again the next night. Our loader gives every row a new `payment_id` when it loads it, so the duplicates had unique ids and nothing complained. The bank's own `bank_reference` was identical on both copies.

## What it cost

* Meridia's August was overstated by EUR 51,703.88 (47 payments), 4.7% of the month.
* The August invoice used that number as its success fee base. At Meridia's 15% August rate we billed EUR 7,755.59 too much.

## The fix, at the source

1. `int_payments` now keeps one row per `bank_reference`, the first one loaded. Everything downstream (KPIs, recovery, billing) reads from it, so the fix applies everywhere at once.
2. A check, `bank_file_loaded_twice`, flags any bank transaction loaded more than once and names the file. It is a warning rather than a failure because the model already handles it, but someone should still tell the bank.
3. A check, `bank_reference_unique`, fails the run if a duplicate ever gets past the model.
4. The September invoice carries a correction line for August: a credit of EUR 7,755.59, with the billed base, the right base and the reason on the invoice itself (`output/invoices/2026-09/INV-202609-C03.pdf`). The invoicing script works this out by comparing what was billed for every earlier month with what the data says now, so any future fix to the data turns into a correction automatically instead of someone having to remember.

## Why bank_reference and not account, amount and date

The obvious way to find duplicates is "same account, same amount, same day". In this data that would have found the same 47 rows, because no real payments happen to match that way yet. But it is normal for a customer catching up to pay a missed instalment and the current one on the same day, for the same amount. Those are two real payments, and an amount and date rule would delete one of them, and our fee with it. The bank's reference is the only key that means "this is the same transaction".
