"""
Downloads the real public data this project uses into data/real/.

  bank_calls.csv          UCI Bank Marketing (bank additional full): 41,188 real outbound calls
                          made by a Portuguese bank, May 2008 to November 2010.
                          Moro, Cortez and Rita (2014). CC BY 4.0.
  card_repayment.csv      UCI Default of Credit Card Clients: 30,000 real card customers in
                          Taiwan, six months of repayment status, April to September 2005.
                          Yeh and Lien (2009). CC BY 4.0.
  ecb_rates.zip           ECB euro foreign exchange reference rates, the official daily file.

It tries the official source first and falls back to a public copy on GitHub, then checks the
file is the size the source says it should be. If a file is already there it is left alone.

Run:  python src/get_real_data.py
"""

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data" / "real"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "collections-analytics/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def first_working(sources):
    for label, url, parse in sources:
        try:
            out = parse(fetch(url))
            print(f"    from {label}")
            return out
        except Exception as e:  # noqa: BLE001  any failure means try the next source
            print(f"    {label} did not work ({type(e).__name__}), trying the next source")
    sys.exit("Could not download it from any source. Download it by hand and put it in data/real/.")


def bank_calls():
    def from_uci(raw):
        outer = zipfile.ZipFile(io.BytesIO(raw))
        inner = zipfile.ZipFile(io.BytesIO(outer.read("bank-additional.zip")))
        return pd.read_csv(io.BytesIO(inner.read("bank-additional/bank-additional-full.csv")), sep=";")

    df = first_working([
        ("UCI", "https://archive.ics.uci.edu/static/public/222/bank+marketing.zip", from_uci),
        ("GitHub copy", "https://raw.githubusercontent.com/selva86/datasets/master/bank-full.csv",
         lambda raw: pd.read_csv(io.BytesIO(raw), sep=";")),
    ])
    assert len(df) == 41188 and (df.y == "yes").sum() == 4640, "bank calls file is not the one UCI publishes"
    return df


def card_repayment():
    def from_uci(raw):
        z = zipfile.ZipFile(io.BytesIO(raw))
        name = next(n for n in z.namelist() if n.endswith(".xls"))
        return pd.read_excel(io.BytesIO(z.read(name)), header=1)

    df = first_working([
        ("UCI", "https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip", from_uci),
        ("GitHub copy", "https://raw.githubusercontent.com/MatteoM95/default-of-credit-card-clients-dataset-analisys/"
                        "main/dataset/default_of_credit_card_clients.csv", lambda raw: pd.read_csv(io.BytesIO(raw))),
    ])
    assert len(df) == 30000 and df["default payment next month"].sum() == 6636, "card file is not the one UCI publishes"
    return df


def ecb_rates():
    def check(raw):
        z = zipfile.ZipFile(io.BytesIO(raw))
        head = z.read(z.namelist()[0])[:200].decode()
        assert head.startswith("Date,USD"), "not the ECB history file"
        return raw

    return first_working([
        ("ECB", "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip", check),
        ("GitHub copy (currencyconverter package)",
         "https://raw.githubusercontent.com/alexprengere/currencyconverter/master/currency_converter/eurofxref-hist.zip", check),
    ])


def main():
    REAL.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("bank_calls.csv", "Bank calls", lambda p: bank_calls().to_csv(p, index=False)),
        ("card_repayment.csv", "Card repayment", lambda p: card_repayment().to_csv(p, index=False)),
        ("ecb_rates.zip", "ECB rates", lambda p: p.write_bytes(ecb_rates())),
    ]
    for name, label, save in jobs:
        path = REAL / name
        if path.exists():
            print(f"  {label}: already in data/real/{name}")
            continue
        print(f"  {label}:")
        save(path)
        print(f"    saved data/real/{name} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
