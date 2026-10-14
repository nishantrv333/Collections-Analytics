"""
Builds a realistic set of raw exports for an AI collections platform working for four banks:
one in the UK, one in the UAE, one in Spain and one in Mexico.

No collections company publishes call level data tied to payments (it is personal financial
data), so the platform data itself is simulated. What is real:

  * FX rates are the ECB's published daily reference rates (data/real/ecb_rates.zip).
  * Public holidays are the real 2026 calendars for England, the UAE, Spain and Mexico, from
    the holidays package. Nobody is called on one and banks send no payment files on them.
  * Calling hours follow each market's rules: 09:00 to 20:00 on weekdays in the UAE (Central
    Bank consumer protection rules), and a stated policy in markets where the regulator only
    says "not at unreasonable times" (the UK's FCA, CONC 7.3).
  * How fast each extra call loses its chance of working, and how much less likely customers
    further behind are to pay, come from real data (config/calibration.json, built by
    src/analyse_real_data.py). Everything else is an assumption, listed in docs/real_data.md.

Tables written to data/raw/:

  clients, contracts         the four banks, their calling rules and what each one pays us
  public_holidays            the real holiday calendars used
  accounts                   the file a bank sends when it places overdue accounts with us
  contact_attempts           every call, WhatsApp, SMS and email
  promises, promise_instalments   promises to pay and the schedule behind each one
  payments                   the banks' daily payment files, including reversals
  fx_rates                   ECB reference rates
  invoices_issued            what finance already billed for June, July and August
  experiment_assignments     which accounts got agent v4.2 and which got v4.3

A few problems are put in on purpose, because real data always has some. docs/ explains how
each one was found.

Run:  python src/generate_data.py
"""

from __future__ import annotations

import calendar
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import holidays
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REAL = ROOT / "data" / "real"
CALIBRATION = ROOT / "config" / "calibration.json"
SEED = 31
UTC = timezone.utc

FIRST_PLACEMENT = date(2026, 6, 1)
LAST_PLACEMENT = date(2026, 9, 18)
DATA_END = date(2026, 9, 30)

CLIENTS = [
    dict(client_id="C01", name="Northgate Bank", country="GB", currency="GBP", tz="Europe/London",
         product="credit_card", daily=140, bal_median=950, bal_sigma=0.85, go_live=date(2026, 6, 1),
         languages={"en": 1.0}, whatsapp=False, answer_mult=0.95, keep_mult=1.02, ref_prefix="NGB",
         file_prefix="northgate", methods={"direct_debit": 0.35, "card": 0.45, "bank_transfer": 0.20},
         call_hours=(8, 21), calls_on_saturday=True, holiday_calendar=("GB", "ENG")),
    dict(client_id="C02", name="Desert Finance", country="AE", currency="AED", tz="Asia/Dubai",
         product="personal_loan", daily=110, bal_median=5200, bal_sigma=0.75, go_live=date(2026, 6, 1),
         languages={"ar": 0.50, "en": 0.35, "hi": 0.15}, whatsapp=True, answer_mult=1.00, keep_mult=1.00,
         ref_prefix="DSF", file_prefix="desert", methods={"bank_transfer": 0.50, "card": 0.50},
         call_hours=(9, 20), calls_on_saturday=False, holiday_calendar=("AE", None)),
    dict(client_id="C03", name="Banco Meridia", country="ES", currency="EUR", tz="Europe/Madrid",
         product="consumer_loan", daily=100, bal_median=850, bal_sigma=0.80, go_live=date(2026, 6, 1),
         languages={"es": 0.88, "ca": 0.12}, whatsapp=True, answer_mult=1.05, keep_mult=1.00, ref_prefix="BMR",
         file_prefix="meridia", methods={"direct_debit": 0.45, "bank_transfer": 0.25, "card": 0.30},
         call_hours=(9, 21), calls_on_saturday=True, holiday_calendar=("ES", None)),
    dict(client_id="C04", name="Lumen Pay", country="MX", currency="MXN", tz="America/Mexico_City",
         product="bnpl", daily=100, bal_median=4200, bal_sigma=0.70, go_live=date(2026, 6, 1),
         languages={"es-MX": 1.0}, whatsapp=True, answer_mult=0.85, keep_mult=0.95, ref_prefix="LMP",
         file_prefix="lumen", methods={"card": 0.55, "cash_voucher": 0.30, "bank_transfer": 0.15},
         call_hours=(9, 21), calls_on_saturday=True, holiday_calendar=("MX", None)),
]
CLIENT_BY_ID = {c["client_id"]: c for c in CLIENTS}


def load_calibration():
    cal = {"attempt_decay": 0.82, "pay_ratio_by_dpd_bucket": {"0_30": 1.0, "31_60": 0.47, "61_90": 0.37}}
    if CALIBRATION.exists():
        cal.update(json.loads(CALIBRATION.read_text()))
    else:
        print("config/calibration.json not found, using the default calibration")
    return cal


CAL = load_calibration()
ATTEMPT_DECAY = CAL["attempt_decay"]                      # real: bank calls
PAY_RATIO = CAL["pay_ratio_by_dpd_bucket"]                # real: card repayment

BUCKETS = ["0_30", "31_60", "61_90"]
BUCKET_P = [0.50, 0.30, 0.20]
BUCKET_DPD = {"0_30": (5, 30), "31_60": (31, 60), "61_90": (61, 90)}

# Assumptions (levels). The shapes across debt age come from the real data where it has them.
P_GOOD_NUMBER = {"0_30": 0.85, "31_60": 0.76, "61_90": 0.66}
P_ANSWER = {"0_30": 0.33, "31_60": 0.26, "61_90": 0.20}
HOUR_WEIGHT = {8: .5, 9: .6, 10: 1.3, 11: 1.3, 12: 1.1, 13: .6, 14: .6, 15: .8, 16: .9, 17: 1.0, 18: 1.2, 19: 1.1, 20: .7}
HOUR_MULT = {8: .85, 9: .90, 10: 1.25, 11: 1.25, 12: 1.15, 13: .80, 14: .80, 15: .95, 16: 1.0, 17: 1.05,
             18: 1.15, 19: 1.10, 20: .95}

RPC_RESULTS = ["paid_on_call", "promise_to_pay", "hardship", "callback", "refused", "dispute"]
RPC_PROBS = {
    "0_30": [0.22, 0.48, 0.06, 0.07, 0.13, 0.04],
    "31_60": [0.14, 0.44, 0.09, 0.08, 0.19, 0.06],
    "61_90": [0.08, 0.38, 0.12, 0.08, 0.27, 0.07],
}
# v4.3 is the affordability first negotiation flow. It asks about the customer's situation
# before asking for money, so more calls end in a plan and slightly fewer in a payment on the spot.
V43_PROMISE_LIFT = {"0_30": 0.03, "31_60": 0.27, "61_90": 0.29}
V43_PAID_ON_CALL_DROP = 0.01
P_INSTALMENTS = {"control": 0.35, "treatment": 0.40}
KEEP_FIRST = {"0_30": 0.86, "31_60": 0.74, "61_90": 0.62}
SELF_CURE = {b: round(0.60 * PAY_RATIO[b], 4) for b in BUCKETS}
REVERSAL_P = {"direct_debit": 0.07, "card": 0.015, "bank_transfer": 0.003, "cash_voucher": 0.0}
# The agent's Hindi is weaker than its Arabic and English: more calls end with "call me back"
# and fewer in a promise, while customers refuse no more often. Found in docs/product_review.md.
HINDI_PROMISE_TO_CALLBACK = 0.35
HINDI_TALK_MULT = 1.25

EXPERIMENT = dict(experiment_id="agent_v43_negotiation", clients={"C01", "C02", "C03", "C04"},
                  start=date(2026, 6, 15), end=date(2026, 7, 31))
# A deploy on Lumen's integration pinned every new account to control for four days.
LUMEN_BUG = ("C04", date(2026, 7, 20), date(2026, 7, 23))
# Meridia's SFTP upload timed out and their system sent this file a second time.
DUPLICATED_FILE = "meridia_payments_20260814.csv"

_TZ = {}


def tz(name):
    if name not in _TZ:
        _TZ[name] = ZoneInfo(name)
    return _TZ[name]


def to_utc(d: date, hour: int, minute: int, tzname: str) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz(tzname)).astimezone(UTC)


def holiday_calendar(client):
    country, subdiv = client["holiday_calendar"]
    return holidays.country_holidays(country, subdiv=subdiv, years=2026, language="en_US")


HOLIDAYS = {c["client_id"]: holiday_calendar(c) for c in CLIENTS}


def is_business_day(d: date, client) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS[client["client_id"]]


def next_business_day(d: date, client) -> date:
    d = d + timedelta(days=1)
    while not is_business_day(d, client):
        d += timedelta(days=1)
    return d


def to_business_day(d: date, client) -> date:
    while not is_business_day(d, client):
        d += timedelta(days=1)
    return d


def can_call(d: date, client) -> bool:
    if d in HOLIDAYS[client["client_id"]] or d.weekday() == 6:
        return False
    return d.weekday() < 5 or client["calls_on_saturday"]


def to_call_day(d: date, client) -> date:
    while not can_call(d, client):
        d += timedelta(days=1)
    return d


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def pick(rng, options: dict):
    keys = list(options)
    return keys[rng.choice(len(keys), p=np.array(list(options.values())))]


def pick_hour(rng, client, lo=None, hi=None):
    start, end = client["call_hours"]
    hours = [h for h in range(start, end) if (lo is None or h >= lo) and (hi is None or h <= hi)]
    w = np.array([HOUR_WEIGHT[h] for h in hours])
    return int(rng.choice(hours, p=w / w.sum()))


class AccountSim:
    """Simulates one account from placement to the end of the data."""

    def __init__(self, rng, client, acc, variant):
        self.rng = rng
        self.c = client
        self.acc = acc
        self.bucket = acc["bucket"]
        self.balance = acc["balance"]
        self.placed = acc["placed_date"]
        self.hindi = acc["language"] == "hi"
        self.treat = variant == "treatment"
        self.agent = "v4.3" if self.treat else "v4.2"
        self.paid = 0.0
        self.attempts = []
        self.promises = []
        self.payments = []
        self.good_number = rng.random() < P_GOOD_NUMBER[self.bucket]
        self.traced = False
        self.had_rpc = False

    # events
    def attempt(self, d, hour, minute, channel, outcome, result=None, talk=0):
        if d > DATA_END:
            return None
        self.attempts.append(dict(
            account_id=self.acc["account_id"], channel=channel,
            started_at_utc=to_utc(d, hour, minute, self.c["tz"]),
            outcome=outcome, call_result=result, talk_seconds=int(talk),
            agent_version=self.agent if channel == "voice" else None))
        return len(self.attempts) - 1

    def message(self, d, channel, hour=None):
        if d > DATA_END:
            return
        hour = hour if hour is not None else int(self.rng.integers(9, 19))
        r = self.rng.random()
        outcome = "failed" if r < 0.04 else ("read" if channel == "whatsapp" and r < 0.64 else "delivered")
        self.attempt(d, hour, int(self.rng.integers(0, 60)), channel, outcome)

    def payment(self, d, amount, method):
        rng = self.rng
        if method in ("direct_debit", "bank_transfer"):
            d = to_business_day(d, self.c)
            hour = int(rng.integers(6, 10)) if method == "direct_debit" else int(rng.integers(8, 19))
        else:
            hour = int(rng.integers(8, 24))
        if d > DATA_END:
            return False
        amount = round(min(amount, self.balance - self.paid), 2)
        if amount < 1:
            return False
        self.paid += amount
        idx = len(self.payments)
        self.payments.append(dict(account_id=self.acc["account_id"], client_id=self.c["client_id"],
                                  paid_date=d, hour=hour, minute=int(rng.integers(0, 60)),
                                  amount=amount, method=method, payment_type="payment", reverses=None))
        if rng.random() < REVERSAL_P[method]:
            rd = to_business_day(d + timedelta(days=int(rng.integers(3, 21))), self.c)
            if rd <= DATA_END:
                self.paid -= amount
                self.payments.append(dict(account_id=self.acc["account_id"], client_id=self.c["client_id"],
                                          paid_date=rd, hour=int(rng.integers(6, 12)), minute=int(rng.integers(0, 60)),
                                          amount=-amount, method=method, payment_type="reversal", reverses=idx))
        return True

    # calling
    def dial(self, d, hour, k):
        """One outbound voice attempt. Returns (right party reached, minute)."""
        rng = self.rng
        minute = int(rng.integers(0, 60))
        if not self.good_number:
            r = rng.random()
            if r < 0.30:
                self.attempt(d, hour, minute, "voice", "invalid_number")
            elif r < 0.45:
                self.attempt(d, hour, minute, "voice", "wrong_party", talk=rng.integers(25, 90))
            elif r < 0.70:
                self.attempt(d, hour, minute, "voice", "voicemail", talk=rng.integers(18, 40))
            else:
                self.attempt(d, hour, minute, "voice", "no_answer")
            return False, minute
        p = P_ANSWER[self.bucket] * self.c["answer_mult"] * HOUR_MULT[hour] * (ATTEMPT_DECAY ** k)
        if rng.random() < p:
            if rng.random() < 0.12:
                self.attempt(d, hour, minute, "voice", "wrong_party", talk=rng.integers(25, 90))
                return False, minute
            return True, minute
        if rng.random() < 0.35:
            self.attempt(d, hour, minute, "voice", "voicemail", talk=rng.integers(18, 40))
        else:
            self.attempt(d, hour, minute, "voice", "no_answer")
        return False, minute

    def rpc(self, d, hour, minute, allow_callback=True):
        rng = self.rng
        self.had_rpc = True
        probs = list(RPC_PROBS[self.bucket])
        if self.treat:
            lift = V43_PROMISE_LIFT[self.bucket]
            probs[0] -= V43_PAID_ON_CALL_DROP
            probs[1] += lift + V43_PAID_ON_CALL_DROP
            rest = probs[2] + probs[3] + probs[4] + probs[5]  # the lift comes out of every other outcome evenly
            for i in (2, 3, 4, 5):
                probs[i] -= lift * probs[i] / rest
        if self.hindi:
            moved = probs[1] * HINDI_PROMISE_TO_CALLBACK
            probs[1] -= moved
            probs[3] += moved
        if not allow_callback:
            probs[1] += probs[3]
            probs[3] = 0
        probs = np.array(probs) / sum(probs)
        result = RPC_RESULTS[rng.choice(len(RPC_RESULTS), p=probs)]
        talk = {"paid_on_call": rng.normal(330, 70), "promise_to_pay": rng.normal(300, 80),
                "hardship": rng.normal(430, 90), "callback": rng.normal(90, 30),
                "refused": rng.normal(180, 60), "dispute": rng.normal(240, 70)}[result]
        if self.hindi:
            talk *= HINDI_TALK_MULT
        a = self.attempt(d, hour, minute, "voice", "right_party", result, max(40, talk))
        if result == "paid_on_call":
            amt = self.balance if rng.random() < 0.7 else self.balance * rng.uniform(0.3, 0.6)
            self.payment(d, amt, "card")
        elif result == "promise_to_pay":
            self.promise(d, "voice_agent", a)
        elif result == "hardship":
            self.message(d, "email", hour)
            if rng.random() < 0.45:
                self.promise(d + timedelta(days=int(rng.integers(7, 15))), "affordability_review", None,
                             forced_n=6, keep_first=0.70)
        elif result == "callback" and allow_callback:
            nd = to_call_day(d + timedelta(days=1), self.c)
            h = pick_hour(rng, self.c)
            m = int(rng.integers(0, 60))
            if nd <= DATA_END and rng.random() < 0.6:
                self.rpc(nd, h, m, allow_callback=False)
            elif nd <= DATA_END:
                self.attempt(nd, h, m, "voice", "no_answer")
        elif result == "refused" and rng.random() < 0.15:
            self.payment(d + timedelta(days=int(rng.integers(5, 30))),
                         self.balance * rng.uniform(0.2, 0.6), "card")

    def follow_up(self, start, n):
        """Calls after a broken promise. Returns (date, hour, minute) of a contact, or None."""
        rng = self.rng
        d = to_call_day(start, self.c)
        for k in range(n):
            if d > DATA_END:
                return None
            h = pick_hour(rng, self.c)
            ok, m = self.dial(d, h, k + 2)
            if ok:
                return d, h, m
            d = to_call_day(d + timedelta(days=int(rng.integers(1, 3))), self.c)
        return None

    def method(self):
        return pick(self.rng, self.c["methods"])

    def promise(self, d, created_by, attempt_idx, forced_n=None, keep_first=None, single_amount=None):
        rng = self.rng
        if d > DATA_END:
            return
        remaining = round(self.balance - self.paid, 2)
        if remaining < 5:
            return
        if single_amount is not None:
            n, total = 1, round(min(single_amount, remaining), 2)
        else:
            p_inst = P_INSTALMENTS["treatment" if self.treat else "control"]
            n = forced_n or (int(rng.choice([2, 3, 4, 6], p=[.3, .35, .2, .15])) if rng.random() < p_inst else 1)
            total = remaining
        first_due = d + timedelta(days=int(rng.integers(2, 11) if n == 1 else rng.integers(3, 15)))
        base = round(total / n, 2)
        amounts = [base] * (n - 1) + [round(total - base * (n - 1), 2)]
        dues = [add_months(first_due, i) for i in range(n)]
        self.promises.append(dict(account_id=self.acc["account_id"], attempt_idx=attempt_idx,
                                  created_date=d, created_by=created_by, n_instalments=n,
                                  total_amount=total, dues=dues, amounts=amounts))
        for due in dues:
            self.message(due - timedelta(days=1), "whatsapp" if self.c["whatsapp"] else "sms")

        if keep_first is None:
            keep_first = KEEP_FIRST[self.bucket] * self.c["keep_mult"] + (0.04 if n > 1 else 0) - (0.02 if self.treat else 0)
        prev = None
        for i, (due, amt) in enumerate(zip(dues, amounts)):
            if due > DATA_END:
                break
            p = keep_first if i == 0 else (0.88 if prev else 0.22)
            kept = rng.random() < p
            if kept:
                delay = int(rng.choice([-2, -1, 0, 0, 0, 1, 1, 2, 3]))
                pay_amt = amt if rng.random() < 0.93 else amt * rng.uniform(0.5, 0.9)
                self.payment(max(d, due + timedelta(days=delay)), pay_amt, self.method())
            else:
                if rng.random() < 0.15:
                    self.payment(due + timedelta(days=int(rng.integers(5, 16))), amt * rng.uniform(0.2, 0.5), self.method())
                if i == 0 and created_by != "follow_up":
                    hit = self.follow_up(due + timedelta(days=4), 3)
                    if hit:
                        hd, hh, hm = hit
                        if rng.random() < 0.45:
                            a = self.attempt(hd, hh, hm, "voice", "right_party", "promise_to_pay", rng.normal(260, 60))
                            self.promise(hd, "follow_up", a, single_amount=amt, keep_first=0.55)
                            kept = True
                        else:
                            self.attempt(hd, hh, hm, "voice", "right_party", "refused", rng.normal(180, 50))
            prev = kept

    # the whole account
    def run(self):
        rng, c, d0 = self.rng, self.c, self.placed
        first_contact_day = to_call_day(d0, c)
        self.message(first_contact_day, "sms", c["call_hours"][0] + 1)
        if self.acc["has_email"]:
            self.message(first_contact_day, "email", c["call_hours"][0] + 1)
        for off in (1, 3, 7):
            self.message(to_call_day(d0 + timedelta(days=off), c), "whatsapp" if c["whatsapp"] else "sms")

        offsets = [0, 1, 2, 4, 6, 8, 11, 14, 18, 23, 28, 34]
        k = 0
        last_day = None
        for off in offsets:
            d = to_call_day(d0 + timedelta(days=off), c)
            if d > DATA_END or k >= 12:
                break
            if d == last_day:
                continue
            last_day = d
            if off == 0:
                hours = [pick_hour(rng, c, lo=13, hi=16)]
            else:
                hours = [pick_hour(rng, c, hi=c["call_hours"][1] - 5)]
                if rng.random() < 0.3:
                    hours.append(min(c["call_hours"][1] - 1, hours[0] + int(rng.integers(4, 7))))
            got = False
            for h in hours:
                ok, m = self.dial(d, h, k)
                k += 1
                if ok:
                    self.rpc(d, h, m)
                    got = True
                    break
            if got:
                break
            if k >= 4 and not self.good_number and not self.traced:
                # skip tracing finds a working number about half the time
                self.traced = True
                self.good_number = rng.random() < 0.5

        if not self.had_rpc and rng.random() < SELF_CURE[self.bucket] * (1.3 if c["client_id"] == "C04" else 1.0):
            amt = self.balance if rng.random() < 0.55 else self.balance * rng.uniform(0.3, 0.7)
            self.payment(d0 + timedelta(days=int(rng.integers(2, 46))), amt, "card")
        return self


def placement_days(client):
    d = max(FIRST_PLACEMENT, client["go_live"])
    while d <= LAST_PLACEMENT:
        if is_business_day(d, client):
            yield d
        d += timedelta(days=1)


def assign_variant(rng, client_id, d):
    if client_id not in EXPERIMENT["clients"] or not (EXPERIMENT["start"] <= d <= EXPERIMENT["end"]):
        return None
    if client_id == LUMEN_BUG[0] and LUMEN_BUG[1] <= d <= LUMEN_BUG[2]:
        return "control"
    return "treatment" if rng.random() < 0.5 else "control"


def ecb_rates():
    """The ECB's real daily reference rates for the currencies we need. The ECB does not publish
    AED; the dirham is pegged at 3.6725 to the US dollar, so it is derived from the USD rate."""
    path = REAL / "ecb_rates.zip"
    if not path.exists():
        raise SystemExit("data/real/ecb_rates.zip is missing. Run python src/get_real_data.py first.")
    z = zipfile.ZipFile(path)
    df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), na_values="N/A")
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df = df[(df.Date >= FIRST_PLACEMENT - timedelta(days=7)) & (df.Date <= DATA_END)]
    out = df.melt(id_vars="Date", value_vars=["GBP", "USD", "MXN"], var_name="currency", value_name="units_per_eur")
    aed = df[["Date"]].assign(currency="AED", units_per_eur=(df["USD"] * 3.6725).round(4))
    out = pd.concat([out, aed]).rename(columns={"Date": "rate_date"}).dropna()
    return out.sort_values(["rate_date", "currency"]).reset_index(drop=True)


def holiday_table():
    rows = []
    for c in CLIENTS:
        country, subdiv = c["holiday_calendar"]
        for d, name in sorted(HOLIDAYS[c["client_id"]].items()):
            if FIRST_PLACEMENT - timedelta(days=7) <= d <= DATA_END:
                rows.append(dict(country=country, region=subdiv or "", holiday_date=d, name=name))
    return pd.DataFrame(rows)


def main():
    rng = np.random.default_rng(SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    fx = ecb_rates()

    accounts, attempts, promises, instalments, payments, assignments = [], [], [], [], [], []
    acc_n = 0
    promise_n = 0
    for c in CLIENTS:
        for d in placement_days(c):
            for _ in range(rng.poisson(c["daily"])):
                acc_n += 1
                bucket = BUCKETS[rng.choice(3, p=BUCKET_P)]
                lo, hi = BUCKET_DPD[bucket]
                balance = round(float(np.clip(rng.lognormal(np.log(c["bal_median"]), c["bal_sigma"]),
                                              c["bal_median"] * 0.08, c["bal_median"] * 12)), 2)
                acc = dict(account_id=f"A{acc_n:06d}", client_id=c["client_id"],
                           external_ref=f"{c['ref_prefix']}{rng.integers(10**8, 10**9)}",
                           product=c["product"], dpd_at_placement=int(rng.integers(lo, hi + 1)),
                           placed_at_utc=to_utc(d, 6, int(rng.integers(0, 50)), c["tz"]),
                           balance_at_placement=balance, currency=c["currency"],
                           language=pick(rng, c["languages"]), has_email=bool(rng.random() < 0.8),
                           bucket=bucket, placed_date=d, balance=balance)
                variant = assign_variant(rng, c["client_id"], d)
                if variant:
                    assignments.append(dict(account_id=acc["account_id"], experiment_id=EXPERIMENT["experiment_id"],
                                            variant=variant, assigned_at_utc=acc["placed_at_utc"] + timedelta(minutes=2)))
                sim = AccountSim(rng, c, acc, variant).run()
                accounts.append({k: acc[k] for k in ["account_id", "client_id", "external_ref", "product",
                                                     "dpd_at_placement", "placed_at_utc", "balance_at_placement",
                                                     "currency", "language", "has_email"]})
                attempt_offset = len(attempts)
                attempts += sim.attempts
                for p in sim.promises:
                    promise_n += 1
                    pid = f"PR{promise_n:06d}"
                    promises.append(dict(promise_id=pid, account_id=p["account_id"],
                                         attempt_row=None if p["attempt_idx"] is None else attempt_offset + p["attempt_idx"],
                                         created_date=p["created_date"], created_by=p["created_by"],
                                         n_instalments=p["n_instalments"], total_amount=p["total_amount"]))
                    for i, (due, amt) in enumerate(zip(p["dues"], p["amounts"]), start=1):
                        instalments.append(dict(promise_id=pid, instalment_no=i, due_date=due, amount=amt))
                pay_offset = len(payments)
                for p in sim.payments:
                    p = dict(p)
                    if p["reverses"] is not None:
                        p["reverses"] = pay_offset + p["reverses"]
                    payments.append(p)

    # attempts
    att = pd.DataFrame(attempts)
    att.insert(0, "attempt_id", [f"T{i:07d}" for i in range(1, len(att) + 1)])
    att["started_at_utc"] = att["started_at_utc"].map(lambda x: x.strftime("%Y-%m-%d %H:%M:%S"))

    # promises: created_at comes from the call that produced it
    pr = pd.DataFrame(promises)
    pr["attempt_id"] = pr["attempt_row"].map(lambda r: None if pd.isna(r) else att.at[int(r), "attempt_id"])
    pr["created_at_utc"] = pr["attempt_row"].map(lambda r: None if pd.isna(r) else att.at[int(r), "started_at_utc"])
    acc_tz = {a["account_id"]: CLIENT_BY_ID[a["client_id"]]["tz"] for a in accounts}
    missing = pr["created_at_utc"].isna()
    pr.loc[missing, "created_at_utc"] = [
        to_utc(d, 11, 0, acc_tz[a]).strftime("%Y-%m-%d %H:%M:%S")
        for d, a in zip(pr.loc[missing, "created_date"], pr.loc[missing, "account_id"])]
    pr = pr[["promise_id", "account_id", "attempt_id", "created_at_utc", "created_by", "n_instalments", "total_amount"]]
    inst = pd.DataFrame(instalments)

    # payments, the way they arrive: one file per business day per bank, by that bank's calendar
    pay = pd.DataFrame(payments)
    pay["file_date"] = [next_business_day(d, CLIENT_BY_ID[c]) for d, c in zip(pay["paid_date"], pay["client_id"])]
    pay = pay[pay["file_date"] <= DATA_END].copy()  # paid at the end of September, arrives in October
    pay["source_file"] = [f"{CLIENT_BY_ID[c]['file_prefix']}_payments_{d:%Y%m%d}.csv" for c, d in zip(pay["client_id"], pay["file_date"])]
    pay["paid_at_utc"] = [to_utc(d, h, m, CLIENT_BY_ID[c]["tz"]).strftime("%Y-%m-%d %H:%M:%S")
                          for d, h, m, c in zip(pay["paid_date"], pay["hour"], pay["minute"], pay["client_id"])]
    pay["loaded_at_utc"] = [datetime(d.year, d.month, d.day, 3, int(rng.integers(0, 40))).strftime("%Y-%m-%d %H:%M:%S")
                            for d in pay["file_date"]]
    pay["bank_reference"] = [f"{CLIENT_BY_ID[c]['ref_prefix']}TX{rng.integers(10**11, 10**12)}" for c in pay["client_id"]]
    ref_by_row = pay["bank_reference"].to_dict()
    pay["reverses_bank_reference"] = pay["reverses"].map(lambda r: None if pd.isna(r) else ref_by_row.get(int(r)))
    pay["currency"] = pay["client_id"].map(lambda c: CLIENT_BY_ID[c]["currency"])

    # the file Meridia sent twice
    dup = pay[pay["source_file"] == DUPLICATED_FILE].copy()
    dup["loaded_at_utc"] = "2026-08-15 03:12:00"
    pay = pd.concat([pay, dup], ignore_index=True).sort_values(["loaded_at_utc", "client_id", "paid_at_utc"], kind="stable")
    pay.insert(0, "payment_id", [f"P{i:07d}" for i in range(1, len(pay) + 1)])
    pay_out = pay[["payment_id", "client_id", "account_id", "bank_reference", "payment_type", "reverses_bank_reference",
                   "amount", "currency", "method", "paid_at_utc", "source_file", "loaded_at_utc"]]

    # what finance billed for June to August (built from the raw files, before anyone deduplicated)
    pay["billing_month"] = pay["file_date"].map(lambda d: d.strftime("%Y-%m"))
    issued = (pay[pay["billing_month"] < "2026-09"].groupby(["client_id", "billing_month"], as_index=False)["amount"].sum()
              .rename(columns={"amount": "billed_collected_base"}))
    issued["billed_collected_base"] = issued["billed_collected_base"].round(2)
    issued["contract_currency"] = issued["client_id"].map(lambda c: CLIENT_BY_ID[c]["currency"])
    issued["invoice_number"] = [f"INV-{m.replace('-', '')}-{c}" for c, m in zip(issued["client_id"], issued["billing_month"])]
    issued["issued_on"] = issued["billing_month"].map(lambda m: (date(int(m[:4]), int(m[5:]), 1) + timedelta(days=34)).replace(day=3))
    issued = issued[["invoice_number", "client_id", "billing_month", "billed_collected_base", "contract_currency", "issued_on"]]

    # reference tables
    clients = pd.DataFrame([dict(client_id=c["client_id"], name=c["name"], country=c["country"], currency=c["currency"],
                                 timezone=c["tz"], product=c["product"], go_live=c["go_live"],
                                 call_start_hour=c["call_hours"][0], call_end_hour=c["call_hours"][1],
                                 calls_on_saturday=c["calls_on_saturday"],
                                 holiday_country=c["holiday_calendar"][0], holiday_region=c["holiday_calendar"][1] or "")
                            for c in CLIENTS])
    contracts = pd.DataFrame([
        dict(contract_id="K01", client_id="C01", valid_from="2026-06-01", valid_to="2027-05-31", contract_currency="GBP",
             invoice_currency="GBP", success_fee_pct=0.12, tier_threshold=100000, success_fee_pct_above=0.09,
             fee_per_voice_minute=0, fee_per_message=0, platform_fee_monthly=0, monthly_minimum=0),
        dict(contract_id="K02", client_id="C02", valid_from="2026-06-01", valid_to="2027-05-31", contract_currency="AED",
             invoice_currency="AED", success_fee_pct=0.08, tier_threshold=None, success_fee_pct_above=None,
             fee_per_voice_minute=0, fee_per_message=0, platform_fee_monthly=15000, monthly_minimum=0),
        dict(contract_id="K03A", client_id="C03", valid_from="2026-06-01", valid_to="2026-08-31", contract_currency="EUR",
             invoice_currency="EUR", success_fee_pct=0.15, tier_threshold=None, success_fee_pct_above=None,
             fee_per_voice_minute=0.09, fee_per_message=0.010, platform_fee_monthly=0, monthly_minimum=4000),
        dict(contract_id="K03B", client_id="C03", valid_from="2026-09-01", valid_to="2027-08-31", contract_currency="EUR",
             invoice_currency="EUR", success_fee_pct=0.14, tier_threshold=None, success_fee_pct_above=None,
             fee_per_voice_minute=0.09, fee_per_message=0.010, platform_fee_monthly=0, monthly_minimum=4000),
        dict(contract_id="K04", client_id="C04", valid_from="2026-06-01", valid_to="2027-05-31", contract_currency="MXN",
             invoice_currency="USD", success_fee_pct=0.10, tier_threshold=None, success_fee_pct_above=None,
             fee_per_voice_minute=1.80, fee_per_message=0.15, platform_fee_monthly=0, monthly_minimum=50000),
    ])
    asg = pd.DataFrame(assignments)
    asg["assigned_at_utc"] = asg["assigned_at_utc"].map(lambda x: x.strftime("%Y-%m-%d %H:%M:%S"))
    acc_df = pd.DataFrame(accounts)
    acc_df["placed_at_utc"] = acc_df["placed_at_utc"].map(lambda x: x.strftime("%Y-%m-%d %H:%M:%S"))

    out = {
        "clients": clients, "contracts": contracts, "public_holidays": holiday_table(), "accounts": acc_df,
        "contact_attempts": att, "promises": pr, "promise_instalments": inst, "payments": pay_out,
        "fx_rates": fx, "invoices_issued": issued, "experiment_assignments": asg,
    }
    for name, df in out.items():
        df.to_csv(RAW / f"{name}.csv", index=False)
        print(f"{name:<24}{len(df):>9,} rows")


if __name__ == "__main__":
    main()
