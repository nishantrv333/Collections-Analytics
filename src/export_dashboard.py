"""
Writes the files the dashboard reads, to output/dashboard/.

The dashboard lets people filter by market, debt age and placement month and then works out
every rate itself, so most of these files are small summed tables ("cubes"): counts and sums
at the level the filters need, never ratios, because ratios cannot be added up again. Every
number comes from the warehouse or from the outputs of the other steps.

Run:  python src/export_dashboard.py
"""

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
OUT = ROOT / "output" / "dashboard"

QUERIES = {
    "markets": """
        select client_id, client_name,
               case country when 'GB' then 'UK' when 'AE' then 'UAE' when 'ES' then 'Spain' else 'Mexico' end as market,
               currency, timezone, call_start_hour, call_end_hour, calls_on_saturday
        from stg_clients order by client_id
    """,
    # one row per bank, placement month, debt age and language
    "cube_accounts": """
        select client_id, placed_month, dpd_bucket, language,
               count(*) as accounts,
               round(sum(balance_eur), 2) as balance_eur,
               sum(voice_attempts) as voice_calls,
               sum((voice_attempts > 0)::int) as called,
               sum(messages_sent) as messages,
               sum(was_reached::int) as reached,
               coalesce(sum(calls_to_first_rpc) filter (where was_reached), 0) as calls_to_reach_sum,
               sum((promises_made > 0 or paid_on_call)::int) as agreed,
               sum((promises_made > 0)::int) as with_promise,
               sum(paid_on_call::int) as paid_on_call,
               sum(flagged_hardship::int) as hardship,
               sum(raised_dispute::int) as disputes,
               sum((collected_to_date > 0)::int) as paid_any,
               sum(is_fully_paid::int) as paid_full,
               round(sum(collected_to_date / placement_units_per_eur), 2) as collected_eur,
               round(coalesce(sum(balance_eur) filter (where collected_d30 is not null), 0), 2) as bal_d30,
               round(coalesce(sum(collected_d30 / placement_units_per_eur), 0), 2) as col_d30,
               round(coalesce(sum(balance_eur) filter (where collected_d60 is not null), 0), 2) as bal_d60,
               round(coalesce(sum(collected_d60 / placement_units_per_eur), 0), 2) as col_d60,
               coalesce(sum(first_instalment_matured::int), 0) as inst_due,
               coalesce(sum(first_instalment_kept::int), 0) as inst_kept
        from fct_accounts
        group by all order by all
    """,
    # recovery curves: cumulative euros collected by day since placement, per bank, month and debt age
    "curve_cells": """
        select client_id, placed_month, dpd_bucket, count(*) as accounts, round(sum(balance_eur), 2) as balance_eur,
               least(90, (select as_of_date from stg_run_date) - max(placed_date) + 1) as max_day
        from fct_accounts group by all order by all
    """,
    "cube_curves": """
        with cells as (
            select client_id, placed_month, dpd_bucket,
                   least(90, (select as_of_date from stg_run_date) - max(placed_date) + 1) as max_day
            from fct_accounts group by all
        ),
        flows as (
            select a.client_id, a.placed_month, a.dpd_bucket, cf.day_n,
                   sum(cast(cf.net_amount as double) / a.placement_units_per_eur) as eur
            from int_account_cashflow cf join fct_accounts a using (account_id)
            where cf.day_n between 0 and 89
            group by all
        ),
        grid as (
            select c.client_id, c.placed_month, c.dpd_bucket, d.day
            from cells c cross join (select unnest(range(1, 91)) as day) d
            where d.day <= c.max_day
        )
        select g.client_id, g.placed_month, g.dpd_bucket, g.day,
               round(sum(coalesce(f.eur, 0)) over (partition by g.client_id, g.placed_month, g.dpd_bucket order by g.day), 2) as cum_eur
        from grid g
        left join flows f on f.client_id = g.client_id and f.placed_month = g.placed_month
                         and f.dpd_bucket = g.dpd_bucket and f.day_n = g.day - 1
        order by 1, 2, 3, 4
    """,
    "cube_calls": """
        select a.client_id, a.placed_month, a.dpd_bucket, t.outcome, count(*) as calls, sum(t.billable_minutes) as minutes
        from stg_contact_attempts t join fct_accounts a using (account_id)
        where t.is_voice group by all order by all
    """,
    "cube_messages": """
        select a.client_id, a.placed_month, a.dpd_bucket, t.channel, t.outcome, count(*) as messages
        from stg_contact_attempts t join fct_accounts a using (account_id)
        where not t.is_voice group by all order by all
    """,
    "cube_conversations": """
        select a.client_id, a.placed_month, a.dpd_bucket, a.language, t.agent_version, t.call_result,
               count(*) as conversations, sum(t.talk_seconds) as talk_seconds
        from stg_contact_attempts t join fct_accounts a using (account_id)
        where t.is_right_party_contact group by all order by all
    """,
    # current agent only, so the v4.3 test does not move the contact numbers
    "cube_hours": """
        with v as (
            select a.client_id, hour(t.started_at_local) as local_hour, t.is_right_party_contact as reached, t.agent_version,
                   least(row_number() over (partition by t.account_id order by t.started_at_utc, t.attempt_id), 8) as call_number
            from stg_contact_attempts t join fct_accounts a using (account_id)
            where t.is_voice
        )
        select client_id, local_hour, call_number, count(*) as calls, sum(reached::int) as reached
        from v where agent_version = 'v4.2' group by all order by all
    """,
    "cube_attempts": """
        with v as (
            select a.client_id, t.account_id, t.is_right_party_contact as reached, t.billable_minutes, t.agent_version,
                   row_number() over (partition by t.account_id order by t.started_at_utc, t.attempt_id) as call_number
            from stg_contact_attempts t join fct_accounts a using (account_id)
            where t.is_voice
        ),
        firsts as (select account_id, min(call_number) filter (where reached) as first_rpc from v group by 1)
        select v.client_id, v.call_number, count(*) as calls, sum(v.reached::int) as first_reached, sum(v.billable_minutes) as minutes
        from v join firsts f using (account_id)
        where v.agent_version = 'v4.2' and v.call_number <= 12 and (f.first_rpc is null or v.call_number <= f.first_rpc)
        group by all order by all
    """,
    "cube_promises": """
        select a.client_id, a.placed_month, a.dpd_bucket, p.created_by, p.n_instalments,
               count(*) as promises, round(sum(p.total_amount / a.placement_units_per_eur), 2) as promised_eur
        from stg_promises p join fct_accounts a using (account_id)
        group by all order by all
    """,
    # kept: at least 95% of what was due by 3 days after the due date; partial: something towards it; broken: nothing
    "cube_instalments": """
        select a.client_id, a.placed_month, a.dpd_bucket, i.instalment_no,
               count(*) filter (where i.is_matured) as due,
               count(*) filter (where i.is_kept) as kept,
               count(*) filter (where i.is_matured and not i.is_kept
                                and i.paid_by_grace_end > i.cumulative_due - i.amount + 0.01) as partial,
               count(*) filter (where i.is_matured and not i.is_kept
                                and i.paid_by_grace_end <= i.cumulative_due - i.amount + 0.01) as broken
        from int_instalments i join fct_accounts a using (account_id)
        group by all order by all
    """,
    "cube_payments": """
        select client_id, paid_month, method, payment_type, count(*) as payments, round(sum(amount_eur), 2) as eur
        from int_payments group by all order by all
    """,
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.csv"):
        old.unlink()
    con = duckdb.connect(str(DB), read_only=True, config={"threads": 1})
    for name, sql in QUERIES.items():
        df = con.execute(sql).df()
        for col in df.columns:  # DuckDB sums of whole numbers arrive as floats; write them as whole numbers
            if df[col].dtype.kind == "f" and df[col].notna().all() and (df[col] % 1 == 0).all() and not col.endswith("eur"):
                df[col] = df[col].astype("int64")
        df.to_csv(OUT / f"{name}.csv", index=False)
    con.close()

    exp = ROOT / "output" / "experiment"
    r = pd.read_csv(exp / "results.csv")
    seg = pd.read_csv(exp / "results_by_debt_age.csv")[["metric", "control", "treatment", "difference", "ci_low", "ci_high", "p_value"]]
    allr = pd.concat([r, seg], ignore_index=True)
    ids = {
        "Recovery within 60 days (primary)": ("rec60", "primary"),
        "Recovery within 60 days, 0 to 30 days past due": ("rec60_0_30", "by debt age"),
        "Recovery within 60 days, 31 to 90 days past due": ("rec60_31_90", "by debt age"),
        "Recovery within 30 days": ("rec30", "secondary"),
        "Promise made, of customers reached": ("promise", "secondary"),
        "First instalment kept": ("kept", "secondary"),
        "Reached the customer (guardrail)": ("reached", "guardrail"),
        "Dispute raised (guardrail)": ("dispute", "guardrail"),
    }
    allr.insert(0, "metric_id", allr.metric.map(lambda m: ids[m][0]))
    allr.insert(2, "kind", allr.metric.map(lambda m: ids[m][1]))
    allr["order"] = allr.metric_id.map({k: i for i, k in enumerate(v[0] for v in ids.values())})
    allr.sort_values("order").drop(columns="order").to_csv(OUT / "experiment_results.csv", index=False)
    pd.read_csv(exp / "recovery_curve_by_variant.csv").to_csv(OUT / "experiment_curves.csv", index=False)
    pd.read_csv(exp / "older_debt_by_market.csv").to_csv(OUT / "experiment_markets.csv", index=False)
    s = json.loads((exp / "summary.json").read_text())
    pd.DataFrame([dict(
        assigned_control=s["assigned"]["control"], assigned_treatment=s["assigned"]["treatment"], split_p_assigned=s["srm_p_value_all"],
        analysed_control=s["analysed"]["control"], analysed_treatment=s["analysed"]["treatment"], split_p_analysed=s["srm_p_value_clean"],
        excluded_accounts=s["accounts_assigned"] - s["accounts_analysed"], aa_sd_points=round(s["aa_sd_points"], 4),
        minimum_detectable_effect_points=round(s["minimum_detectable_effect_points"], 4),
        monthly_balance_31_90_eur=round(s["monthly_balance_31_90_eur"], 2),
        extra_collected_per_month_eur=round(s["extra_collected_per_month_eur"], 2),
        bank_days=len(pd.read_csv(exp / "split_by_bank_and_day.csv")),
        broken_from=pd.to_datetime(min(d["date"] for d in s["broken_days"])).strftime("%-d %B"),
        broken_to=pd.to_datetime(max(d["date"] for d in s["broken_days"])).strftime("%-d %B"))]).to_csv(OUT / "experiment_summary.csv", index=False)

    inv_dir = ROOT / "output" / "invoices" / "2026-09"
    pd.read_csv(inv_dir / "invoice_summary.csv")[[
        "invoice_number", "client_id", "client_name", "contract_id", "contract_currency", "invoice_currency", "fx_rate",
        "success_fee_base", "bank_files", "total_contract_currency", "total_invoice_currency", "total_eur"]].to_csv(OUT / "invoices.csv", index=False)
    pd.read_csv(inv_dir / "invoice_lines.csv").to_csv(OUT / "invoice_lines.csv", index=False)
    files = pd.concat([pd.read_csv(f) for f in sorted(inv_dir.glob("*_bank_files.csv"))], ignore_index=True)
    files.to_csv(OUT / "bank_files.csv", index=False)

    pd.read_csv(ROOT / "output" / "checks" / "check_results.csv").to_csv(OUT / "checks.csv", index=False)
    inv = ROOT / "output" / "investigations"
    pd.read_csv(inv / "meridia_daily_payments_august.csv").to_csv(OUT / "duplicate_file_days.csv", index=False)
    pd.read_csv(inv / "weekend_fx_impact_by_client.csv").to_csv(OUT / "weekend_fx_impact.csv", index=False)
    real = pd.read_csv(ROOT / "output" / "real_data" / "call_attempts.csv")
    real[real.call_number <= 12][["call_number", "customers_called_this_many_times", "worked_on_this_call", "chance_this_call_works"]] \
        .to_csv(OUT / "real_bank_calls.csv", index=False)

    for p in sorted(OUT.glob("*.csv")):
        print(f"  {p.name:<28}{p.stat().st_size / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
