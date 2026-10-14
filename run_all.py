"""
Runs the whole project from nothing: the real data and its analysis, the platform data, the
warehouse, the checks, then the invoices, the experiment, the product review and the
investigations. Stops at the first failure.

Run:  python run_all.py
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    ("Getting the real data", ["src/get_real_data.py"]),
    ("Analysing the real data", ["src/analyse_real_data.py"]),
    ("Generating the platform data", ["src/generate_data.py"]),
    ("Building the warehouse", ["src/build_models.py"]),
    ("Running data checks", ["src/run_checks.py"]),
    ("Invoicing September", ["src/invoicing.py", "--month", "2026-09"]),
    ("Reading the v4.3 experiment", ["src/experiment.py"]),
    ("Product review", ["src/product_review.py"]),
    ("Investigations", ["src/investigations.py"]),
    ("Files for the dashboard", ["src/export_dashboard.py"]),
]

if __name__ == "__main__":
    start = time.time()
    for title, args in STEPS:
        print(f"\n== {title}")
        result = subprocess.run([sys.executable, *args], cwd=ROOT)
        if result.returncode != 0:
            sys.exit(f"Stopped at: {title}")
    print(f"\nDone in {time.time() - start:.0f}s")
