"""
Runs every query in sql/checks against the warehouse. Each check returns the rows that break
a rule, so an empty result is a pass. A failing "error" check stops the run; a "warn" check
prints what it found and carries on.

Run:  python src/run_checks.py
"""

import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
CHECKS = ROOT / "sql" / "checks"
OUT = ROOT / "output" / "checks"


def main():
    con = duckdb.connect(str(DB), read_only=True, config={"threads": 1})
    failed = 0
    results = []
    for f in sorted(CHECKS.glob("*.sql")):
        sql = f.read_text()
        severity = re.search(r"severity:\s*(\w+)", sql).group(1)
        rows = con.execute(sql).df()
        purpose = " ".join(re.search(r"severity:\s*\w+\s*(.*?)\*/", sql, re.S).group(1).split())
        results.append(dict(check=f.stem, severity=severity, status="pass" if rows.empty else ("fail" if severity == "error" else "warn"),
                            rows_found=len(rows), what_it_checks=purpose))
        if rows.empty:
            print(f"  pass   {f.stem}")
            continue
        label = "FAIL" if severity == "error" else "warn"
        print(f"  {label}   {f.stem}: {len(rows)} row(s)")
        print("         " + rows.head(5).to_string(index=False).replace("\n", "\n         "))
        if severity == "error":
            failed += 1
    con.close()
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(OUT / "check_results.csv", index=False)
    if failed:
        sys.exit(f"{failed} check(s) failed")
    print("All error level checks passed.")


if __name__ == "__main__":
    main()
