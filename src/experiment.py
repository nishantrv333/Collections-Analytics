"""
Reads the agent v4.3 test: did the affordability first negotiation flow collect more money?

What was agreed before the test started:
  * unit: the account. Accounts placed 15 June to 31 July 2026 at Meridia, Northgate and
    Lumen were split 50/50 when they arrived.
  * primary metric: share of placed balance collected within 60 days, net of reversals.
    60 days because v4.3 offers more instalment plans, and most of that money lands after
    day 30. Euros at the placement date rate for balance and payments alike.
  * read it split by debt age as well (0 to 30 days past due, 31 to 90), because the agent
    is already set up differently for those two groups.
  * guardrails: reach rate (v4.3 changes what is said, not who is called, so this should not
    move) and dispute rate (should not go up).

Run:  python src/experiment.py
"""

import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
OUT = ROOT / "output" / "experiment"
CHARTS = ROOT / "docs" / "img"
EXPERIMENT_ID = "agent_v43_negotiation"
N_BOOT = 2000
SEED = 11

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def load(con):
    acc = con.execute("""
        select a.*, e.experiment_id
        from fct_accounts a
        left join stg_experiment_assignments e using (account_id)
    """).df()
    acc["placed_date"] = pd.to_datetime(acc["placed_date"])
    acc["age_group"] = np.where(acc.dpd_bucket == "0_30", "0 to 30 days", "31 to 90 days")
    acc["stratum"] = acc.client_id + "|" + acc.dpd_bucket
    for n in (30, 60):
        acc[f"c{n}_eur"] = acc[f"collected_d{n}"].astype(float) / acc.placement_units_per_eur
    return acc


def sample_ratio_check(exp):
    """Is the split really 50/50? Checked overall and for every bank and day."""
    counts = exp.experiment_variant.value_counts()
    overall_p = stats.chisquare([counts.get("control", 0), counts.get("treatment", 0)]).pvalue
    daily = (exp.groupby(["client_id", "placed_date"])
             .agg(accounts=("account_id", "size"), treatment=("experiment_variant", lambda v: (v == "treatment").sum()))
             .reset_index())
    daily["treatment_share"] = daily.treatment / daily.accounts
    daily["p_value"] = [stats.binomtest(int(t), int(n), 0.5).pvalue for t, n in zip(daily.treatment, daily.accounts)]
    # About 130 bank days get tested, so a strict cut off stops normal chance from flagging a day.
    daily["broken"] = daily.p_value < 0.05 / len(daily)
    return overall_p, counts, daily


def ratio(df, col):
    return df[col].sum() / df.balance_eur.sum()


def stratified_diff(c, t, col):
    """Difference in recovery within each bank x debt age group, weighted by placed balance.
    Removes noise from one group happening to get more big balances or more old debt."""
    gc = c.groupby("stratum")[[col, "balance_eur"]].sum()
    gt = t.groupby("stratum")[[col, "balance_eur"]].sum()
    w = gc.balance_eur + gt.balance_eur
    d = gt[col] / gt.balance_eur - gc[col] / gc.balance_eur
    return float((w * d).sum() / w.sum())


def bootstrap(c, t, col, rng, n=N_BOOT):
    """Resample accounts with replacement inside each stratum and variant, recompute the
    stratified difference, repeat n times. Done with index arrays so 2,000 rounds take seconds."""
    strata = sorted(set(c.stratum) & set(t.stratum))
    num, den = np.zeros(n), 0.0

    def boot_ratio(df):
        a, b = df[col].to_numpy(float), df.balance_eur.to_numpy(float)
        idx = rng.integers(0, len(df), (n, len(df)))
        return a[idx].sum(axis=1) / b[idx].sum(axis=1)

    for s in strata:
        cs, ts = c[c.stratum == s], t[t.stratum == s]
        w = cs.balance_eur.sum() + ts.balance_eur.sum()
        num += w * (boot_ratio(ts) - boot_ratio(cs))
        den += w
    return num / den


def summarise(name, unit, est, boot):
    lo, hi = np.percentile(boot, [2.5, 97.5])
    p = 2 * stats.norm.sf(abs(est) / boot.std())
    return dict(metric=name, unit=unit, difference=est, ci_low=lo, ci_high=hi, p_value=p)


def rate(df, num, den):
    d = df[den].sum() if den != "rows" else len(df)
    return df[num].sum() / d


def aa_test(con, rng, n=500):
    """Before trusting a lift, how much does the metric move by pure chance? Take June accounts
    (before the test), split them at random many times, and look at the spread of differences."""
    june = load(con)
    june = june[june.placed_date < "2026-06-15"].copy()
    diffs = []
    for _ in range(n):
        mask = rng.random(len(june)) < 0.5
        diffs.append(stratified_diff(june[~mask], june[mask], "c60_eur"))
    return np.array(diffs), len(june)


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    CHARTS.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    con = duckdb.connect(str(DB), read_only=True)
    acc = load(con)
    exp = acc[acc.experiment_id == EXPERIMENT_ID].copy()

    # 1. Is the split clean?
    p_all, counts, daily = sample_ratio_check(exp)
    broken = daily[daily.broken]
    daily.to_csv(OUT / "split_by_bank_and_day.csv", index=False)
    bad_keys = set(zip(broken.client_id, broken.placed_date))
    clean = exp[[(c, d) not in bad_keys for c, d in zip(exp.client_id, exp.placed_date)]].copy()
    p_clean = stats.chisquare(clean.experiment_variant.value_counts().reindex(["control", "treatment"]).values).pvalue

    c = clean[clean.experiment_variant == "control"].copy()
    t = clean[clean.experiment_variant == "treatment"].copy()

    # 2. Primary metric and the rest
    rows = []
    est = stratified_diff(c, t, "c60_eur")
    boot60 = bootstrap(c, t, "c60_eur", rng)
    rows.append(summarise("Recovery within 60 days (primary)", "points", est, boot60))
    est30 = stratified_diff(c, t, "c30_eur")
    rows.append(summarise("Recovery within 30 days", "points", est30,
                          bootstrap(c, t, "c30_eur", rng)))

    clean["has_promise"] = clean.promises_made > 0
    c = clean[clean.experiment_variant == "control"].copy()
    t = clean[clean.experiment_variant == "treatment"].copy()

    def prop_diff(num, base_c, base_t):
        a, b = base_c[num].mean(), base_t[num].mean()
        se = np.sqrt(a * (1 - a) / len(base_c) + b * (1 - b) / len(base_t))
        d = b - a
        return dict(difference=d, ci_low=d - 1.96 * se, ci_high=d + 1.96 * se, p_value=2 * stats.norm.sf(abs(d) / se),
                    control=a, treatment=b)

    reached_c, reached_t = c[c.was_reached], t[t.was_reached]
    matured_c = c[c.first_instalment_matured.fillna(False).astype(bool)].copy()
    matured_t = t[t.first_instalment_matured.fillna(False).astype(bool)].copy()
    for df in (matured_c, matured_t):
        df["kept"] = df.first_instalment_kept.fillna(False).astype(bool)
    others = [
        ("Reached the customer (guardrail)", "was_reached", c, t),
        ("Promise made, of customers reached", "has_promise", reached_c, reached_t),
        ("First instalment kept", "kept", matured_c, matured_t),
        ("Dispute raised (guardrail)", "raised_dispute", c, t),
    ]
    for name, col, bc, bt in others:
        r = prop_diff(col, bc, bt)
        rows.append(dict(metric=name, unit="points", **{k: r[k] for k in ("difference", "ci_low", "ci_high", "p_value")}))
    results = pd.DataFrame(rows)

    # levels, for context
    levels = {
        "Recovery within 60 days (primary)": (ratio(c, "c60_eur"), ratio(t, "c60_eur")),
        "Recovery within 30 days": (ratio(c, "c30_eur"), ratio(t, "c30_eur")),
        "Reached the customer (guardrail)": (c.was_reached.mean(), t.was_reached.mean()),
        "Promise made, of customers reached": (reached_c.has_promise.mean(), reached_t.has_promise.mean()),
        "First instalment kept": (matured_c.kept.mean(), matured_t.kept.mean()),
        "Dispute raised (guardrail)": (c.raised_dispute.mean(), t.raised_dispute.mean()),
    }
    results["control"] = results.metric.map(lambda m: levels[m][0])
    results["treatment"] = results.metric.map(lambda m: levels[m][1])
    results = results[["metric", "control", "treatment", "difference", "ci_low", "ci_high", "p_value"]]
    results.to_csv(OUT / "results.csv", index=False)

    # 3. The pre agreed split by debt age
    seg_rows = []
    for g in ("0 to 30 days", "31 to 90 days"):
        cg, tg = c[c.age_group == g], t[t.age_group == g]
        e = stratified_diff(cg, tg, "c60_eur")
        b = bootstrap(cg, tg, "c60_eur", rng)
        r = summarise(f"Recovery within 60 days, {g} past due", "points", e, b)
        r.update(control=ratio(cg, "c60_eur"), treatment=ratio(tg, "c60_eur"), accounts=len(cg) + len(tg),
                 promise_control=cg[cg.was_reached].has_promise.mean(), promise_treatment=tg[tg.was_reached].has_promise.mean(),
                 paid_on_call_control=cg[cg.was_reached].paid_on_call.mean(), paid_on_call_treatment=tg[tg.was_reached].paid_on_call.mean())
        seg_rows.append(r)
    segments = pd.DataFrame(seg_rows)
    segments.to_csv(OUT / "results_by_debt_age.csv", index=False)

    # Not agreed in advance, so only a consistency check: does the older debt gain show up in every market?
    market_rows = []
    for bank, g_c in c[c.age_group == "31 to 90 days"].groupby("client_name"):
        g_t = t[(t.age_group == "31 to 90 days") & (t.client_name == bank)]
        e = stratified_diff(g_c, g_t, "c60_eur")
        b = bootstrap(g_c, g_t, "c60_eur", rng)
        lo, hi = np.percentile(b, [2.5, 97.5])
        market_rows.append(dict(bank=bank, accounts=len(g_c) + len(g_t), control=ratio(g_c, "c60_eur"),
                                treatment=ratio(g_t, "c60_eur"), difference=e, ci_low=lo, ci_high=hi))
    markets = pd.DataFrame(market_rows)
    markets.to_csv(OUT / "older_debt_by_market.csv", index=False)

    # 4. How big is chance? A/A splits of June accounts
    aa, aa_n = aa_test(con, rng)
    pd.DataFrame({"difference": aa}).to_csv(OUT / "aa_differences.csv", index=False)
    aa_sd = aa.std()
    mde = 2.8 * aa_sd * np.sqrt(aa_n / len(clean))  # 80% power, 5% two sided, scaled to the test's size

    # 5. Curves by variant
    flows = con.execute("""
        select cf.account_id, cf.day_n, cf.net_amount
        from int_account_cashflow cf
        where cf.day_n between 0 and 59
    """).df()
    con.close()
    flows = flows.merge(clean[["account_id", "experiment_variant", "age_group", "placement_units_per_eur"]], on="account_id")
    flows["eur"] = flows.net_amount.astype(float) / flows.placement_units_per_eur
    curve_rows = []
    for (g, v), df in flows.groupby(["age_group", "experiment_variant"]):
        bal = clean[(clean.experiment_variant == v) & (clean.age_group == g)].balance_eur.sum()
        by_day = df.groupby("day_n").eur.sum().reindex(range(60), fill_value=0).cumsum() / bal
        for d, val in by_day.items():
            curve_rows.append(dict(age_group=g, variant=v, day=d + 1, recovery=val))
    curves = pd.DataFrame(curve_rows)
    curves.to_csv(OUT / "recovery_curve_by_variant.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6), dpi=150, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, g in zip(axes, ("0 to 30 days", "31 to 90 days")):
        style(ax)
        ends = {v: curves[(curves.variant == v) & (curves.age_group == g)].recovery.iloc[-1] for v in ("control", "treatment")}
        gap = 0.035 - abs(ends["control"] - ends["treatment"])
        label_y = dict(ends)
        if gap > 0:  # keep end labels from sitting on top of each other
            hi, lo = sorted(ends, key=ends.get, reverse=True)
            label_y[hi] += gap / 2
            label_y[lo] -= gap / 2
        for v, label, color in (("control", "v4.2", "#8a8984"), ("treatment", "v4.3", BLUE)):
            cv = curves[(curves.variant == v) & (curves.age_group == g)]
            ax.plot(cv.day, cv.recovery, color=color, linewidth=2)
            ax.annotate(f"{label}  {ends[v]:.1%}", (60, label_y[v]), xytext=(6, 0),
                        textcoords="offset points", color=INK, fontsize=9, va="center", annotation_clip=False)
        ax.set_xlim(1, 60)
        ax.set_ylim(0, 0.62)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.set_title(f"{g} past due at placement", loc="left", color=INK, fontsize=10)
        ax.set_xlabel("Days since placement", color=INK2, fontsize=9)
    fig.suptitle("Share of placed balance collected, v4.3 against v4.2", x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(CHARTS / "experiment_recovery_curves.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)

    # lift chart: one row per result, dot with 95% interval
    plot = pd.concat([results[["metric", "difference", "ci_low", "ci_high"]],
                      segments[["metric", "difference", "ci_low", "ci_high"]]], ignore_index=True)
    order = ["Recovery within 60 days (primary)", "Recovery within 60 days, 0 to 30 days past due",
             "Recovery within 60 days, 31 to 90 days past due", "Recovery within 30 days",
             "Promise made, of customers reached", "First instalment kept",
             "Reached the customer (guardrail)", "Dispute raised (guardrail)"]
    plot = plot.set_index("metric").loc[order].reset_index()
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    y = np.arange(len(plot))[::-1]
    ax.axvline(0, color=INK2, linewidth=1)
    ax.hlines(y, plot.ci_low * 100, plot.ci_high * 100, color=BLUE, linewidth=2)
    ax.scatter(plot.difference * 100, y, color=BLUE, s=36, zorder=3, edgecolor=SURFACE, linewidth=1.5)
    for yi, (_, r) in zip(y, plot.iterrows()):
        ax.annotate(f"{r.difference * 100:+.1f}", (r.ci_high * 100, yi), xytext=(6, 0), textcoords="offset points",
                    color=INK, fontsize=8.5, va="center")
    ax.set_yticks(y)
    ax.set_yticklabels(plot.metric, color=INK, fontsize=9)
    ax.set_xlabel("v4.3 minus v4.2, percentage points, with 95% interval", color=INK2, fontsize=9)
    ax.set_title("What v4.3 changed", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(CHARTS / "experiment_lift.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)

    # What the 31 to 90 result is worth: placed balance in that group per full month, all banks
    full_months = acc[(acc.dpd_bucket != "0_30") & acc.placed_month.isin(["2026-07", "2026-08"])]
    monthly_balance_31_90 = full_months.groupby("placed_month").balance_eur.sum().mean()
    lift_31_90 = float(segments.loc[segments.metric.str.contains("31 to 90"), "difference"].iloc[0])

    summary = dict(
        monthly_balance_31_90_eur=float(monthly_balance_31_90),
        extra_collected_per_month_eur=float(monthly_balance_31_90 * lift_31_90),
        accounts_assigned=int(len(exp)),
        assigned=counts.to_dict(),
        srm_p_value_all=float(p_all),
        broken_days=[dict(client_id=r.client_id, date=str(r.placed_date.date()), accounts=int(r.accounts),
                          treatment=int(r.treatment)) for _, r in broken.iterrows()],
        accounts_analysed=int(len(clean)),
        analysed=clean.experiment_variant.value_counts().to_dict(),
        srm_p_value_clean=float(p_clean),
        aa_sd_points=float(aa_sd * 100),
        aa_accounts=int(aa_n),
        minimum_detectable_effect_points=float(mde * 100),
        results=results.to_dict(orient="records"),
        by_debt_age=segments.to_dict(orient="records"),
    )
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float))

    print(f"Assigned {len(exp):,} accounts: {counts.to_dict()}  split check p = {p_all:.2g}")
    for b in summary["broken_days"]:
        print(f"  broken split: {b}")
    print(f"Analysed {len(clean):,} accounts after dropping broken days, split check p = {p_clean:.2f}")
    print(f"31 to 90 days balance placed per month: EUR {monthly_balance_31_90:,.0f}; "
          f"+{lift_31_90 * 100:.1f} pts is about EUR {monthly_balance_31_90 * lift_31_90:,.0f} more within 60 days")
    print(f"A/A spread (sd) of 60 day recovery: {aa_sd * 100:.2f} pts; minimum detectable effect about {mde * 100:.1f} pts")
    pd.set_option("display.width", 200)
    print(results.round(4).to_string(index=False))
    print(markets.round(4).to_string(index=False))
    print(segments[["metric", "control", "treatment", "difference", "ci_low", "ci_high", "p_value", "accounts",
                    "promise_control", "promise_treatment", "paid_on_call_control", "paid_on_call_treatment"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
