"""
Puts numbers on the two data problems I found, so the write ups in docs/ can point at
something reproducible instead of my memory.

  1. Meridia's 14 August payment file was loaded twice.
  2. Weekend payments had no FX rate and dropped out of every euro total.

For each one it rebuilds the number the old way and the fixed way, side by side.

Run:  python src/investigations.py
"""

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
OUT = ROOT / "output" / "investigations"


def duplicate_payments(con):
    # How it showed up: one day where Meridia's money doubled but the number of people paying did not.
    daily = con.execute("""
        with raw as (
            select paid_date, sum(amount) as amount, count(*) as payment_rows, count(distinct account_id) as accounts
            from stg_payments where client_id = 'C03' and payment_type = 'payment'
              and paid_date between date '2026-08-03' and date '2026-08-21'
            group by 1
        ),
        clean as (
            select paid_date, sum(amount) as amount, count(*) as payment_rows
            from int_payments where client_id = 'C03' and payment_type = 'payment'
              and paid_date between date '2026-08-03' and date '2026-08-21'
            group by 1
        )
        select r.paid_date, dayname(r.paid_date) as weekday,
               r.amount as amount_as_loaded, c.amount as amount_deduplicated,
               r.payment_rows as rows_as_loaded, c.payment_rows as rows_deduplicated,
               r.accounts as distinct_accounts_paying,
               round(r.payment_rows / r.accounts, 2) as rows_per_account
        from raw r join clean c using (paid_date)
        order by 1
    """).df()

    impact = con.execute("""
        with raw as (
            select sum(amount) as amount from stg_payments
            where client_id = 'C03' and strftime(paid_date, '%Y-%m') = '2026-08'
        ),
        clean as (
            select sum(amount) as amount from int_payments
            where client_id = 'C03' and paid_month = '2026-08'
        )
        select raw.amount as august_as_loaded, clean.amount as august_deduplicated,
               raw.amount - clean.amount as overstated_by,
               round((raw.amount - clean.amount) / clean.amount, 4) as overstated_share
        from raw, clean
    """).df()

    # Why I deduplicate on bank_reference and not on (account, amount, date): real customers do pay
    # the same amount twice on the same day, usually a missed instalment plus the current one.
    look_alikes = con.execute("""
        select account_id, client_id, paid_date, amount, count(*) as real_payments,
               string_agg(bank_reference, ' ') as bank_references
        from int_payments
        where payment_type = 'payment'
        group by 1, 2, 3, 4
        having count(*) > 1
        order by paid_date
    """).df()
    return daily, impact, look_alikes


def weekend_fx(con):
    # The first version of the euro conversion: join payments straight to the published rates.
    # Euro payments pass straight through; everything else joins to the published rate for the day.
    old = """
        select p.client_id, p.paid_month, sum(p.amount / f.units_per_eur) as net_collected_eur
        from int_payments p
        join stg_fx_rates f on f.currency = p.currency and f.rate_date = p.paid_date
        where p.currency <> 'EUR'
        group by 1, 2
        union all
        select client_id, paid_month, sum(amount)
        from int_payments
        where currency = 'EUR'
        group by 1, 2
    """
    compare = con.execute(f"""
        with old as ({old}),
        new as (select client_id, paid_month, sum(amount_eur) as net_collected_eur from int_payments group by 1, 2),
        weekend as (
            select client_id, paid_month, sum(amount_eur) filter (where paid_on_weekend) as weekend_eur,
                   count(*) filter (where paid_on_weekend) as weekend_payments, count(*) as payments
            from int_payments group by 1, 2
        )
        select n.client_id, n.paid_month,
               round(coalesce(o.net_collected_eur, 0), 2) as eur_old_join,
               round(n.net_collected_eur, 2) as eur_fixed,
               round(n.net_collected_eur - coalesce(o.net_collected_eur, 0), 2) as missing_eur,
               round(1 - coalesce(o.net_collected_eur, 0) / n.net_collected_eur, 4) as missing_share,
               w.weekend_payments, w.payments
        from new n
        left join old o using (client_id, paid_month)
        join weekend w using (client_id, paid_month)
        order by 1, 2
    """).df()
    return compare


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    daily, impact, look_alikes = duplicate_payments(con)
    fx = weekend_fx(con)
    con.close()
    for col in ("missing_eur", "missing_share"):
        fx[col] = fx[col].where(fx[col].abs() > 1e-6, 0.0)

    daily.to_csv(OUT / "meridia_daily_payments_august.csv", index=False)
    impact.to_csv(OUT / "meridia_duplicate_impact.csv", index=False)
    look_alikes.to_csv(OUT / "same_amount_same_day_real_payments.csv", index=False)
    fx.to_csv(OUT / "weekend_fx_impact.csv", index=False)

    pd.set_option("display.width", 200)
    print("1. Duplicate payment file")
    print(daily.to_string(index=False))
    print(impact.to_string(index=False))
    print(f"Real payments that share account, amount and day with another one: "
          f"{int(look_alikes.real_payments.sum())} payments in {len(look_alikes)} groups, "
          f"{look_alikes.amount.astype(float).mul(look_alikes.real_payments).sum():,.2f} in total")
    print("\n2. Weekend FX")
    print(fx.to_string(index=False))
    by_client = fx.groupby("client_id")[["eur_old_join", "eur_fixed", "missing_eur"]].sum()
    by_client["missing_share"] = (by_client.missing_eur / by_client.eur_fixed).round(4)
    print(by_client.to_string())
    by_client.to_csv(OUT / "weekend_fx_impact_by_client.csv")


if __name__ == "__main__":
    main()
