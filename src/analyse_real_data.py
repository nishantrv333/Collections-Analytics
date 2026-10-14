"""
What real data says about calling customers and about how people in arrears behave, and the
numbers from it that the simulation uses (config/calibration.json).

Two public datasets (see src/get_real_data.py for sources and licences):

  Bank calls       41,188 outbound calls by a Portuguese bank. Used for: how fast the chance of
                   success falls with each extra call, and two traps in reading call data.
  Card repayment   30,000 card customers in Taiwan with six months of repayment status. Used for:
                   how much less likely customers are to pay as they fall further behind.

Run:  python src/analyse_real_data.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data" / "real"
OUT = ROOT / "output" / "real_data"
IMG = ROOT / "docs" / "img"
CONFIG = ROOT / "config"

INK, INK2, GRID, SURFACE, BLUE, MUTED = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb", "#2a78d6", "#a3a29c"


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


# Bank calls

def call_attempts(b):
    """The chance that call number k is the one that works, out of customers who got a k-th call.
    'campaign' is how many times the customer was called, and the last call is the one with
    the outcome, so a yes with campaign = 3 means the third call worked."""
    ks = np.arange(1, 16)
    reached = np.array([(b.campaign >= k).sum() for k in ks])
    worked = np.array([((b.campaign == k) & b.yes).sum() for k in ks])
    df = pd.DataFrame({"call_number": ks, "customers_called_this_many_times": reached, "worked_on_this_call": worked})
    df["chance_this_call_works"] = df.worked_on_this_call / df.customers_called_this_many_times
    df["share_of_all_successes_so_far"] = df.worked_on_this_call.cumsum() / b.yes.sum()
    # fit chance(k) = first * decay^(k-1) on calls 1 to 10, weighting each call by how many customers got it
    fit = df[df.call_number <= 10]
    slope, intercept = np.polyfit(fit.call_number - 1, np.log(fit.chance_this_call_works), 1, w=np.sqrt(fit.customers_called_this_many_times))
    return df, float(np.exp(slope)), float(np.exp(intercept))


def channel_within_month(b):
    """Mobile against landline, compared inside each month. The raw gap mixes in which months
    each was used for: most landline calls were made in May and June 2008."""
    rows = []
    for m, g in b.groupby("month"):
        cell, tel = g[g.contact == "cellular"], g[g.contact == "telephone"]
        if len(cell) >= 100 and len(tel) >= 100:
            rows.append(dict(month=m, mobile_calls=len(cell), landline_calls=len(tel),
                             mobile_success=cell.yes.mean(), landline_success=tel.yes.mean()))
    df = pd.DataFrame(rows)
    w = df.mobile_calls + df.landline_calls
    within_ratio = float((df.mobile_success * w).sum() / (df.landline_success * w).sum())
    raw = b.groupby("contact").yes.mean()
    return df, float(raw["cellular"] / raw["telephone"]), within_ratio


def duration_leak(b):
    """Call duration predicts the outcome very well, but you only know it after the call has
    happened, so a model using it is useless for deciding who to call. Shown by scoring the same
    model with and without it."""
    cats = ["job", "marital", "education", "default", "housing", "loan", "contact", "month", "day_of_week", "poutcome"]
    nums = ["age", "campaign", "pdays", "previous", "emp.var.rate", "cons.price.idx", "cons.conf.idx", "euribor3m", "nr.employed"]
    cv = StratifiedKFold(5, shuffle=True, random_state=7)
    out = {}
    for label, extra in (("with call duration", ["duration"]), ("without call duration", [])):
        pre = ColumnTransformer([("c", OneHotEncoder(handle_unknown="ignore"), cats), ("n", StandardScaler(), nums + extra)])
        model = make_pipeline(pre, LogisticRegression(max_iter=2000))
        out[label] = float(cross_val_score(model, b[cats + nums + extra], b.yes, cv=cv, scoring="roc_auc").mean())
    return out


# Card repayment

STATUS_COLS = ["PAY_6", "PAY_5", "PAY_4", "PAY_3", "PAY_2", "PAY_0"]
MONTHS = ["April", "May", "June", "July", "August", "September"]


def status_counts(t):
    """How many customers had each repayment status in each month. 1 means one month behind."""
    rows = []
    for col, m in zip(STATUS_COLS, MONTHS):
        vc = t[col].value_counts()
        rows.append(dict(month=m, one_month_behind=int(vc.get(1, 0)), two_months_behind=int(vc.get(2, 0)),
                         three_or_more_behind=int(vc[vc.index >= 3].sum()), not_behind=int(vc[vc.index <= 0].sum())))
    return pd.DataFrame(rows)


def paying_by_months_behind(t):
    """Share of customers who did not default the next month, by how far behind they were in
    September. Only September is usable for 'one month behind' (see status_counts)."""
    rows = []
    for k, label in ((1, "1 month behind"), (2, "2 months behind"), (3, "3 months behind")):
        g = t[t.PAY_0 == k]
        rows.append(dict(status=label, customers=len(g), did_not_default_next_month=1 - g["default payment next month"].mean()))
    return pd.DataFrame(rows)


def roll_rates(t):
    """Where customers 2 or 3 months behind in August were in September."""
    def bucket(v):
        return "up to date" if v <= 0 else ("1 month behind" if v == 1 else ("2 months behind" if v == 2 else "3 or more behind"))
    rows = []
    for k in (2, 3):
        g = t[t.PAY_2 == k]
        dist = g.PAY_0.map(bucket).value_counts(normalize=True)
        rows.append({"august_status": f"{k} months behind", "customers": len(g),
                     **{c: float(dist.get(c, 0.0)) for c in ["up to date", "1 month behind", "2 months behind", "3 or more behind"]}})
    return pd.DataFrame(rows)


def charts(attempts, decay, first, paying):
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    a = attempts[attempts.call_number <= 12]
    ax.bar(a.call_number, a.chance_this_call_works * 100, color=BLUE, width=0.6, zorder=2)
    ks = np.linspace(1, 12, 100)
    ax.plot(ks, first * decay ** (ks - 1) * 100, color=INK2, linewidth=1.5, linestyle=(0, (4, 3)), zorder=3)
    ax.text(12.4, first * 0.98 * 100, f"dashed line: fitted, each call {1 - decay:.0%} less\nlikely to work than the one before", ha="right", va="top",
            color=INK, fontsize=9)
    cum = attempts.set_index("call_number").share_of_all_successes_so_far
    ax.text(12.4, first * 0.70 * 100, f"{cum[1]:.0%} of successes on the first call,\n{cum[3]:.0%} by the third, {cum[5]:.0%} by the fifth",
            ha="right", va="top", color=INK2, fontsize=9)
    ax.set_xticks(range(1, 13))
    ax.set_xlabel("Call number", color=INK2, fontsize=9)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(decimals=0))
    ax.set_title("Chance a call works, by how many times the customer had been called (real bank data)", loc="left", color=INK, fontsize=10.5)
    fig.tight_layout()
    fig.savefig(IMG / "real_call_attempts.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    ax.bar(paying.status, paying.did_not_default_next_month * 100, color=BLUE, width=0.5, zorder=2)
    for i, r in paying.iterrows():
        ax.annotate(f"{r.did_not_default_next_month:.0%}  ({r.customers:,} customers)", (i, r.did_not_default_next_month * 100),
                    xytext=(0, 4), textcoords="offset points", ha="center", color=INK, fontsize=9)
    ax.set_ylim(0, 80)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(decimals=0))
    ax.set_title("Card customers who did not default the next month, by how far behind they were (real data)", loc="left", color=INK, fontsize=10.5)
    fig.tight_layout()
    fig.savefig(IMG / "real_paying_by_months_behind.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def main():
    for p in (OUT, IMG, CONFIG):
        p.mkdir(parents=True, exist_ok=True)
    if not (REAL / "bank_calls.csv").exists():
        raise SystemExit("No real data yet. Run python src/get_real_data.py first.")

    b = pd.read_csv(REAL / "bank_calls.csv")
    b["yes"] = b.y == "yes"
    t = pd.read_csv(REAL / "card_repayment.csv")

    attempts, decay, first = call_attempts(b)
    channel, raw_ratio, within_ratio = channel_within_month(b)
    weekday = b.groupby("day_of_week").yes.agg(success_rate="mean", calls="size").reindex(["mon", "tue", "wed", "thu", "fri"]).reset_index()
    month = b.groupby("month").yes.agg(success_rate="mean", calls="size").sort_values("calls", ascending=False).reset_index()
    previous = b.groupby("poutcome").yes.agg(success_rate="mean", calls="size").reset_index()
    leak = duration_leak(b)
    counts = status_counts(t)
    paying = paying_by_months_behind(t)
    rolls = roll_rates(t)

    attempts.to_csv(OUT / "call_attempts.csv", index=False)
    channel.to_csv(OUT / "mobile_vs_landline_by_month.csv", index=False)
    weekday.to_csv(OUT / "success_by_weekday.csv", index=False)
    month.to_csv(OUT / "success_by_month.csv", index=False)
    previous.to_csv(OUT / "success_by_previous_outcome.csv", index=False)
    pd.DataFrame([{"model": k, "auc": v} for k, v in leak.items()]).to_csv(OUT / "duration_leak.csv", index=False)
    counts.to_csv(OUT / "repayment_status_counts.csv", index=False)
    paying.to_csv(OUT / "paying_by_months_behind.csv", index=False)
    rolls.to_csv(OUT / "roll_rates_august_to_september.csv", index=False)
    charts(attempts, decay, first, paying)

    p = paying.set_index("status").did_not_default_next_month
    calibration = {
        "attempt_decay": round(decay, 4),
        "pay_ratio_by_dpd_bucket": {
            "0_30": 1.0,
            "31_60": round(float(p["2 months behind"] / p["1 month behind"]), 4),
            "61_90": round(float(p["3 months behind"] / p["1 month behind"]), 4),
        },
        "notes": {
            "attempt_decay": "Fitted on real bank calls 1 to 10: each call is this many times as likely to work as the one before.",
            "pay_ratio_by_dpd_bucket": "Real card customers not defaulting next month, 2 and 3 months behind, relative to 1 month behind.",
        },
    }
    (CONFIG / "calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")

    pd.set_option("display.width", 200)
    print("Call attempts (real):")
    print(attempts.head(10).round(4).to_string(index=False))
    print(f"  fitted decay per call: {decay:.4f}  (first call {first:.4f})")
    print(f"Mobile against landline: raw {raw_ratio:.2f}x, within month {within_ratio:.2f}x")
    print(channel.round(4).to_string(index=False))
    print(weekday.round(4).to_string(index=False))
    print(month.round(4).to_string(index=False))
    print(previous.round(4).to_string(index=False))
    print("Duration leak, AUC:", {k: round(v, 3) for k, v in leak.items()})
    print(counts.to_string(index=False))
    print(paying.round(4).to_string(index=False))
    print(rolls.round(4).to_string(index=False))
    print("Calibration:", json.dumps(calibration["pay_ratio_by_dpd_bucket"]), "decay", calibration["attempt_decay"])


if __name__ == "__main__":
    main()
