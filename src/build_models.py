"""
Builds the warehouse from the raw CSVs.

Every .sql file under sql/staging, sql/intermediate and sql/marts is one table, named after
the file. A model can use any other model by name, and I work out the build order from that,
so adding a model is just adding a file.

Run:  python src/build_models.py
"""

import re
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "warehouse.duckdb"
SQL = ROOT / "sql"
LAYERS = ["staging", "intermediate", "marts"]
EXPORT = ROOT / "output" / "marts"


def load_models():
    models = {}
    for layer in LAYERS:
        for f in sorted((SQL / layer).glob("*.sql")):
            models[f.stem] = (layer, f.read_text())
    return models


def build_order(models):
    deps = {
        name: {other for other in models if other != name and re.search(rf"\b{other}\b", sql)}
        for name, (_, sql) in models.items()
    }
    order, done = [], set()

    def visit(name, path=()):
        if name in done:
            return
        if name in path:
            raise SystemExit(f"Circular reference: {' > '.join(path + (name,))}")
        for d in sorted(deps[name]):
            visit(d, path + (name,))
        done.add(name)
        order.append(name)

    for name in models:
        visit(name)
    return order


def connect():
    # One thread, so sums come out in the same order and every rerun writes identical files.
    con = duckdb.connect(str(DB), config={"threads": 1})
    for csv in sorted(RAW.glob("*.csv")):
        con.execute(f"create or replace view raw_{csv.stem} as select * from read_csv_auto('{csv}', header = true)")
    return con


def main():
    if not RAW.exists() or not any(RAW.glob("*.csv")):
        sys.exit("No raw data yet. Run python src/generate_data.py first.")
    models = load_models()
    con = connect()
    start = time.time()
    for name in build_order(models):
        layer, sql = models[name]
        t = time.time()
        con.execute(f"create or replace table {name} as\n{sql}")
        rows = con.execute(f"select count(*) from {name}").fetchone()[0]
        print(f"  {layer:<13}{name:<28}{rows:>9,} rows  {time.time() - t:5.2f}s")

    EXPORT.mkdir(parents=True, exist_ok=True)
    for name, (layer, _) in models.items():
        if layer == "marts" and name not in ("fct_payments", "fct_accounts"):
            con.execute(f"copy {name} to '{EXPORT / (name + '.csv')}' (header, delimiter ',')")
    con.close()
    print(f"Built {len(models)} models in {time.time() - start:.1f}s. Marts exported to output/marts/")


if __name__ == "__main__":
    main()
