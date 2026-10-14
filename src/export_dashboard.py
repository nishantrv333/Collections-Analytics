"""
Writes the small, tidy files the dashboard reads. Everything here comes from the marts and
the outputs of the other steps; nothing is calculated for the first time in this file.

Run:  python src/export_dashboard.py
"""

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
OUT = ROOT / "output" / "dashboard"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True, config={"threads": 1})

    con.execute("""
        select k.client_id, c.client_name, c.currency, k.month, k.accounts_placed, k.calls, k.right_party_calls,
               k.rpc_rate_per_call, k.promise_rate, k.paid_on_call_rate, k.first_instalments_due, k.promise_kept_rate,
               k.net_collected, round(k.net_collected_eur, 2) as net_collected_eur, k.reversed
        from kpi_client_month k join stg_clients c using (client_id)
        order by k.client_id, k.month
    """).df().to_csv(OUT / "client_month.csv", index=False)

    con.execute("""
        select r.client_id, coalesce(c.client_name, 'All banks') as client_name, r.placed_month,
               r.days_since_placement, r.accounts, r.recovery_rate
        from kpi_cohort_recovery r left join stg_clients c using (client_id)
        order by 1, 3, 4
    """).df().to_csv(OUT / "cohort_recovery.csv", index=False)

    f = con.execute("select * from kpi_funnel").df()
    f["client_id"] = f.client_id.fillna("ALL")
    f["dpd_bucket"] = f.dpd_bucket.fillna("ALL")
    f.to_csv(OUT / "funnel.csv", index=False)
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

    s = json.loads((exp / "summary.json").read_text())
    pd.DataFrame([
        dict(stage="assigned", control=s["assigned"]["control"], treatment=s["assigned"]["treatment"],
             split_p_value=s["srm_p_value_all"]),
        dict(stage="analysed", control=s["analysed"]["control"], treatment=s["analysed"]["treatment"],
             split_p_value=s["srm_p_value_clean"]),
    ]).to_csv(OUT / "experiment_split.csv", index=False)
    pd.DataFrame([dict(monthly_balance_31_90_eur=round(s["monthly_balance_31_90_eur"], 2),
                       extra_collected_per_month_eur=round(s["extra_collected_per_month_eur"], 2),
                       minimum_detectable_effect_points=round(s["minimum_detectable_effect_points"], 2),
                       excluded_accounts=s["accounts_assigned"] - s["accounts_analysed"])]
                 ).to_csv(OUT / "experiment_value.csv", index=False)

    inv = pd.read_csv(ROOT / "output" / "invoices" / "2026-09" / "invoice_summary.csv")
    lines = pd.read_csv(ROOT / "output" / "invoices" / "2026-09" / "invoice_lines.csv")
    corr = lines[lines.line_type == "correction"].groupby("invoice_number").amount.sum()
    inv["correction"] = inv.invoice_number.map(corr).fillna(0.0)
    inv[["invoice_number", "client_name", "contract_currency", "success_fee_base", "correction", "invoice_currency",
         "total_invoice_currency", "total_eur"]].to_csv(OUT / "invoices.csv", index=False)

    pd.read_csv(ROOT / "output" / "checks" / "check_results.csv").to_csv(OUT / "checks.csv", index=False)

    prod = ROOT / "output" / "product"
    pd.read_csv(prod / "market_scorecard.csv").to_csv(OUT / "market_scorecard.csv", index=False)
    lang = pd.read_csv(prod / "uae_conversations_by_language.csv")
    lang[lang.bank == "Desert Finance"][["language", "conversations", "promise_to_pay_rate", "callback_rate", "refused_rate",
                                         "talk_minutes"]].to_csv(OUT / "uae_languages.csv", index=False)
    pd.read_csv(prod / "reached_by_local_hour.csv").assign(
        share_of_calls=lambda d: d.calls / d.calls.sum()).to_csv(OUT / "call_hours.csv", index=False)
    sim = pd.read_csv(prod / "calls_by_number.csv")[["call_number", "chance_reached"]]
    real = pd.read_csv(ROOT / "output" / "real_data" / "call_attempts.csv")[["call_number", "chance_this_call_works"]]
    both = sim.merge(real, on="call_number").query("call_number <= 10")
    both["simulated_vs_first_call"] = both.chance_reached / both.chance_reached.iloc[0]
    both["real_vs_first_call"] = both.chance_this_call_works / both.chance_this_call_works.iloc[0]
    both.rename(columns={"chance_reached": "simulated_chance", "chance_this_call_works": "real_chance"}).to_csv(
        OUT / "calls_vs_real.csv", index=False)
    pd.read_csv(exp / "older_debt_by_market.csv").to_csv(OUT / "older_debt_by_market.csv", index=False)
    for p in sorted(OUT.glob("*.csv")):
        print(f"  {p.name:<26}{p.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
