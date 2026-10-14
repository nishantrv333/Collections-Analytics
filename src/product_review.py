"""
Product review: how the agent is doing in each market, in each language, call by call and hour
by hour. Uses only accounts on the current agent (v4.2), so the v4.3 test does not blur the
comparison. Writes tables to output/product/ and charts to docs/img/.

Run:  python src/product_review.py
"""

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
OUT = ROOT / "output" / "product"
IMG = ROOT / "docs" / "img"
INK, INK2, GRID, SURFACE, BLUE, ORANGE, MUTED = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb", "#2a78d6", "#eb6834", "#a3a29c"

CURRENT_AGENT = "coalesce(a.experiment_variant, 'control') = 'control'"


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def scorecard(con):
    """One row per market. Accounts placed June to August so every one has had 30 days."""
    return con.execute(f"""
        with acc as (
            select a.* from fct_accounts a
            where {CURRENT_AGENT} and a.placed_date < date '2026-09-01'
        ),
        calls as (
            select t.client_id,
                   count(*) filter (where t.is_right_party_contact) as rpc_calls,
                   count(*) filter (where t.call_result = 'promise_to_pay') as promise_calls,
                   count(*) filter (where t.call_result = 'paid_on_call') as paid_calls,
                   avg(t.talk_seconds / 60.0) filter (where t.is_right_party_contact) as talk_min
            from stg_contact_attempts t join acc a using (account_id)
            group by 1
        )
        select c.client_name as bank, c.country,
               count(*) as accounts,
               avg(a.was_reached::int) as reach_rate,
               avg(a.calls_to_first_rpc) filter (where a.was_reached) as calls_to_reach,
               max(k.promise_calls) / max(k.rpc_calls) as promise_rate,
               max(k.paid_calls) / max(k.rpc_calls) as paid_on_call_rate,
               avg(a.first_instalment_kept::int) filter (where a.first_instalment_matured) as first_instalment_kept,
               sum(a.collected_d30 / a.placement_units_per_eur) / sum(a.balance_eur) as recovery_30d,
               avg(a.raised_dispute::int) as dispute_rate,
               avg(a.flagged_hardship::int) as hardship_rate,
               max(k.talk_min) as talk_minutes_per_conversation
        from acc a join stg_clients c using (client_id) join calls k using (client_id)
        group by c.client_id, c.client_name, c.country
        order by c.client_id
    """).df()


def by_language(con):
    """How conversations end, by language, for the UAE bank (English in the UK as a reference)."""
    df = con.execute(f"""
        select c.client_name as bank, a.language, t.call_result, count(*) as calls, avg(t.talk_seconds) / 60.0 as talk_min
        from stg_contact_attempts t
        join fct_accounts a using (account_id)
        join stg_clients c on c.client_id = a.client_id
        where t.is_right_party_contact and {CURRENT_AGENT} and a.client_id in ('C01', 'C02')
        group by 1, 2, 3
    """).df()
    totals = df.groupby(["bank", "language"]).calls.sum().rename("conversations")
    talk = df.assign(w=df.calls * df.talk_min).groupby(["bank", "language"]).w.sum() / totals
    wide = df.pivot_table(index=["bank", "language"], columns="call_result", values="calls", fill_value=0)
    shares = wide.div(totals, axis=0)
    out = pd.concat([totals, shares.add_suffix("_rate"), talk.rename("talk_minutes")], axis=1).reset_index()
    order = {"ar": 0, "en": 1, "hi": 2}
    out["o"] = out.language.map(order)
    return out.sort_values(["bank", "o"]).drop(columns="o"), wide


def hindi_tests(wide):
    """Hindi against Arabic and English together, inside Desert Finance."""
    uae = wide.loc["Desert Finance"]
    hi, rest = uae.loc["hi"], uae.loc[["ar", "en"]].sum()
    rows = []
    for outcome in ("promise_to_pay", "callback", "refused"):
        a, n1 = hi[outcome], hi.sum()
        b, n2 = rest[outcome], rest.sum()
        _, p = stats.chi2_contingency([[a, n1 - a], [b, n2 - b]])[:2]
        rows.append(dict(outcome=outcome, hindi=a / n1, arabic_and_english=b / n2, difference=a / n1 - b / n2, p_value=p))
    return pd.DataFrame(rows)


def hindi_by_debt_age(con):
    """Same comparison inside each debt age group, to rule out Hindi speakers simply being further behind."""
    return con.execute(f"""
        select a.dpd_bucket, (a.language = 'hi') as hindi, count(*) as conversations,
               avg((t.call_result = 'promise_to_pay')::int) as promise_rate,
               avg((t.call_result = 'callback')::int) as callback_rate,
               avg((t.call_result = 'refused')::int) as refused_rate
        from stg_contact_attempts t join fct_accounts a using (account_id)
        where t.is_right_party_contact and {CURRENT_AGENT} and a.client_id = 'C02'
        group by 1, 2 order by 1, 2
    """).df()


def calls_by_number(con):
    """Chance that call number k reaches the right person, for accounts not reached before it."""
    return con.execute(f"""
        with v as (
            select t.account_id, t.is_right_party_contact, t.billable_minutes,
                   row_number() over (partition by t.account_id order by t.started_at_utc, t.attempt_id) as call_number
            from stg_contact_attempts t join fct_accounts a using (account_id)
            where t.is_voice and {CURRENT_AGENT}
        ),
        before_first as (
            select v.* from v
            left join (select account_id, min(call_number) filter (where is_right_party_contact) as first_rpc from v group by 1) f using (account_id)
            where f.first_rpc is null or v.call_number <= f.first_rpc
        )
        select call_number,
               count(*) as calls,
               sum(is_right_party_contact::int) as first_reached_here,
               avg(is_right_party_contact::int) as chance_reached,
               sum(billable_minutes) as minutes
        from before_first
        where call_number <= 12
        group by 1 order by 1
    """).df()


def by_hour(con):
    """Reach rate by local hour, raw and adjusted for call number. First calls are scheduled in the
    afternoon and first calls work best, so the raw numbers flatter the afternoon. The adjusted
    figure compares each hour with what its mix of call numbers would predict (above 1 is better)."""
    return con.execute(f"""
        with v as (
            select hour(t.started_at_local) as local_hour, t.is_right_party_contact as reached,
                   least(row_number() over (partition by t.account_id order by t.started_at_utc, t.attempt_id), 8) as call_number
            from stg_contact_attempts t join fct_accounts a using (account_id)
            where t.is_voice and {CURRENT_AGENT}
        ),
        base as (select call_number, avg(reached::int) as expected from v group by 1)
        select v.local_hour, count(*) as calls, avg(v.reached::int) as reached_rate,
               avg(case when v.call_number = 1 then 1 else 0 end) as share_first_calls,
               sum(v.reached::int) / sum(b.expected) as reach_vs_expected
        from v join base b using (call_number)
        group by 1 order by 1
    """).df()


def charts(lang, calls, real):
    uae = lang[lang.bank == "Desert Finance"].set_index("language")
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    outcomes = [("promise_to_pay_rate", "Promise to pay"), ("callback_rate", "Asked to call back"), ("refused_rate", "Refused")]
    langs = [("ar", "Arabic", MUTED), ("en", "English", "#6f6e69"), ("hi", "Hindi", BLUE)]
    x = np.arange(len(outcomes))
    for i, (code, name, color) in enumerate(langs):
        vals = [uae.loc[code, o] * 100 for o, _ in outcomes]
        bars = ax.bar(x + (i - 1) * 0.26, vals, 0.24, color=color, label=name, zorder=2)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.0f}%", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8, color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([n for _, n in outcomes], color=INK, fontsize=9)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(decimals=0))
    ax.legend(frameon=False, fontsize=9, ncols=3, loc="upper right")
    ax.set_title("How conversations end at Desert Finance (UAE), by language", loc="left", color=INK, fontsize=10.5)
    fig.tight_layout()
    fig.savefig(IMG / "product_uae_languages.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    sim = calls.set_index("call_number").chance_reached
    r = real.set_index("call_number").chance_this_call_works
    ks = np.arange(1, 11)
    ax.plot(ks, sim.loc[ks] / sim.loc[1], color=BLUE, linewidth=2, marker="o", markersize=4)
    ax.plot(ks, r.loc[ks] / r.loc[1], color=MUTED, linewidth=2, marker="o", markersize=4)
    ends = {"sim": sim.loc[10] / sim.loc[1], "real": r.loc[10] / r.loc[1]}
    gap = 0.07 - abs(ends["sim"] - ends["real"])
    ys = dict(ends)
    if gap > 0:  # keep the two end labels apart
        hi_key = max(ends, key=ends.get)
        lo_key = "real" if hi_key == "sim" else "sim"
        ys[hi_key] += gap / 2
        ys[lo_key] -= gap / 2
    ax.annotate(f"our calls (simulated) {ends['sim']:.0%}", (10, ys["sim"]), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK, annotation_clip=False)
    ax.annotate(f"real bank calls {ends['real']:.0%}", (10, ys["real"]), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK, annotation_clip=False)
    ax.set_xlim(0.7, 10.3)
    ax.set_ylim(0, 1.15)
    ax.set_xticks(ks)
    ax.set_xlabel("Call number", color=INK2, fontsize=9)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_title("Chance a call works, as a share of the first call's chance", loc="left", color=INK, fontsize=10.5)
    fig.tight_layout()
    fig.savefig(IMG / "product_calls_vs_real.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    score = scorecard(con)
    lang, wide = by_language(con)
    tests = hindi_tests(wide)
    hindi_age = hindi_by_debt_age(con)
    calls = calls_by_number(con)
    hours = by_hour(con)
    con.close()

    calls["share_of_first_reaches_so_far"] = calls.first_reached_here.cumsum() / calls.first_reached_here.sum()
    calls["share_of_minutes"] = calls.minutes / calls.minutes.sum()
    real = pd.read_csv(ROOT / "output" / "real_data" / "call_attempts.csv")

    score.to_csv(OUT / "market_scorecard.csv", index=False)
    lang.to_csv(OUT / "uae_conversations_by_language.csv", index=False)
    tests.to_csv(OUT / "hindi_tests.csv", index=False)
    hindi_age.to_csv(OUT / "hindi_by_debt_age.csv", index=False)
    calls.to_csv(OUT / "calls_by_number.csv", index=False)
    hours.to_csv(OUT / "reached_by_local_hour.csv", index=False)
    charts(lang, calls, real)

    pd.set_option("display.width", 220)
    print(score.round(4).to_string(index=False))
    print(lang.round(4).to_string(index=False))
    print(tests.round(4).to_string(index=False))
    print(hindi_age.round(4).to_string(index=False))
    print(calls.round(4).to_string(index=False))
    print(hours.assign(share_of_calls=hours.calls / hours.calls.sum()).round(4).to_string(index=False))


if __name__ == "__main__":
    main()
