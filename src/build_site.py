"""
Builds index.html at the top of the repository: the dashboard as a standalone page that GitHub
Pages can serve, so anyone can open it in a browser without running anything.

It reuses the dashboard page in output/dashboard/index.html as it is and adds what that page
normally gets from its viewer: the data (the CSVs in output/dashboard/, embedded in the page),
a small `dash` helper that hands those rows to the page, d3 for the charts, fonts and colours.
Every number on the site therefore comes from the same files as everything else.

Run:  python src/build_site.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "output" / "dashboard"
OUT = ROOT / "index.html"
REPO_URL = "https://github.com/nishantrv333/Collections-Analytics"

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Collections Analytics</title>
<meta name="description" content="Dashboard for an AI collections agent working for banks in the UK, UAE, Spain and Mexico: markets, product findings, the agent v4.3 test, invoices and data checks.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@400&display=swap">
<style>
/* Layout: one centred column, a thin bar with links on top, the dashboard, then sources. */
:root {
  color-scheme: light;
  --color-bg: #f3f4f6;
  --color-panel: #ffffff;
  --color-fg: #15181d;
  --color-fg-muted: #5b6270;
  --color-border-line: #e1e4e9;
  --color-ok: #1a7f37;
  --color-warn: #9a6700;
  --color-bad: #c42b2b;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --series-5: #e87ba4; --series-6: #008300; --series-7: #6250d6; --series-8: #e34948;
  --cds-chart-grid: #e7e9ed;
  --cds-chart-axis: #b6bcc6;
  --cds-chart-reference: #8a919c;
  --cds-chart-muted: #a9afb9;
  --cds-chart-status-critical: #d03b3b;
  --cds-surface-popover: #ffffff;
  --cds-border: #d9dde3;
  --cds-shadow-popover: 0 4px 16px rgba(15, 20, 30, .10);
  --cds-text-secondary: #5b6270;
  --cds-radius: 8px;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 12px; --cds-pad-lg: 18px; --cds-pad-xl: 24px;
  --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 16px; --cds-gap-lg: 24px; --cds-gap-xl: 36px;
  --cds-font-size-caption: 12.5px; --cds-font-size-body: 15px; --cds-font-size-heading: 16px; --cds-font-size-title: 30px;
  --cds-font-weight-medium: 500;
  --cds-dur-slow: 300ms;
  --font-anthropic-sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-anthropic-serif: "IBM Plex Serif", Georgia, "Times New Roman", serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --color-bg: #0f1114; --color-panel: #181b20; --color-fg: #eceef1; --color-fg-muted: #a2a8b3;
    --color-border-line: #2a2e35; --color-ok: #3fb950; --color-warn: #d29922; --color-bad: #f0605d;
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
    --cds-chart-grid: #262a31; --cds-chart-axis: #4a505a; --cds-chart-reference: #7b828d; --cds-chart-muted: #5f6672;
    --cds-surface-popover: #20242a; --cds-border: #343941; --cds-shadow-popover: 0 4px 16px rgba(0, 0, 0, .45);
    --cds-text-secondary: #a2a8b3;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --color-bg: #0f1114; --color-panel: #181b20; --color-fg: #eceef1; --color-fg-muted: #a2a8b3;
  --color-border-line: #2a2e35; --color-ok: #3fb950; --color-warn: #d29922; --color-bad: #f0605d;
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
  --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
  --cds-chart-grid: #262a31; --cds-chart-axis: #4a505a; --cds-chart-reference: #7b828d; --cds-chart-muted: #5f6672;
  --cds-surface-popover: #20242a; --cds-border: #343941; --cds-shadow-popover: 0 4px 16px rgba(0, 0, 0, .45);
  --cds-text-secondary: #a2a8b3;
}
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font-family: var(--font-anthropic-sans); font-size: var(--cds-font-size-body); line-height: 1.45; }
.site { max-width: 1280px; margin-inline: auto; padding-inline: clamp(16px, 4vw, 40px); padding-block: 0 48px; }
.topbar { display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: baseline; justify-content: space-between; padding-block: 16px; margin-bottom: 20px; border-bottom: 1px solid var(--color-border-line); font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); }
.topbar b { color: var(--color-fg); font-weight: 600; letter-spacing: .02em; }
.topbar nav { display: flex; flex-wrap: wrap; gap: 6px 16px; }
a { color: var(--series-1); text-underline-offset: 2px; }
a:focus-visible, button:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; }
.ca table, .ca svg { max-width: 100%; }
.dash-skeleton { color: transparent; }
.site-foot { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--color-border-line); font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); display: grid; gap: 6px; max-width: 80ch; line-height: 1.55; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
</head>
<body>
<div class="site">
<header class="topbar">
  <span><b>Nishant Vatnal</b> &nbsp;Product data analysis portfolio</span>
  <nav aria-label="Project links">
    <a href="REPO_URL">Code and SQL on GitHub</a>
    <a href="REPO_URL/blob/main/docs/experiment_agent_v43.md">Experiment write up</a>
    <a href="REPO_URL/blob/main/docs/product_review.md">Product review</a>
    <a href="REPO_URL/blob/main/docs/real_data.md">What is real</a>
  </nav>
</header>
<main id="dash-root">
"""

SHIM = """<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script>
/* What the dashboard page normally gets from its viewer: the rows of each file, values worked
   out from them (dash.calc), a redraw when the width changes (dash.onData), and series colours. */
window.dash = (function () {
  const store = {};
  document.querySelectorAll('script[type="text/csv"]').forEach(function (s) {
    const rows = d3.csvParse(s.textContent.trim());
    store[s.dataset.dataset] = { status: 'ok', data: rows, columns: rows.columns, refreshing: false, meta: [] };
  });
  const missing = { status: 'missing', data: [], refreshing: false, meta: [] };
  const listeners = [];
  let lastWidth = 0;
  function runAll() { listeners.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } }); }
  function watch() {
    const root = document.getElementById('dash-root');
    if (window.ResizeObserver && root) {
      new ResizeObserver(function () {
        const w = root.clientWidth;
        if (Math.abs(w - lastWidth) > 1) { lastWidth = w; runAll(); }
      }).observe(root);
    }
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(runAll);
  }
  return {
    data: function (id) { return store[id] || missing; },
    calc: function (id, def) {
      try {
        const args = def.inputs.map(function (i) { return (store[i] || missing).data; });
        store[id] = { status: 'ok', data: def.fn.apply(null, args), refreshing: false, meta: [] };
      } catch (e) {
        console.error('calc ' + id, e);
        store[id] = { status: 'error', data: [], message: String(e), refreshing: false, meta: [] };
      }
    },
    onData: function (fn) {
      listeners.push(fn);
      fn();
      if (listeners.length === 1) watch();
    },
    colors: ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)',
             'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)'],
    refresh: function () {}, params: function () { return {}; },
    setLink: function (name) { try { history.replaceState(null, '', '#' + name); } catch (e) {} },
    setParams: function () {}, resetParams: function () {}
  };
})();
</script>
"""

FOOT = """</main>
<footer class="site-foot">
  <span>The platform data (accounts, calls, promises, payments) is simulated, because call level collections data tied to payments is never published. Exchange rates are the ECB's daily reference rates, public holidays are the real 2026 calendars, and calling hours follow each market's rules.</span>
  <span>How customers behave is calibrated on two real public datasets: UCI Bank Marketing (41,188 bank calls; Moro, Cortez and Rita, 2014) and UCI Default of Credit Card Clients (30,000 card customers; Yeh and Lien, 2009), both CC BY 4.0.</span>
  <span>Every number here is produced by <code>python run_all.py</code> in the <a href="REPO_URL">repository</a>.</span>
</footer>
</div>
</body>
</html>
"""


def main():
    page = (DASH / "index.html").read_text()
    data = []
    for csv in sorted(DASH.glob("*.csv")):
        text = csv.read_text().strip()
        if "</script" in text.lower():
            raise SystemExit(f"{csv.name} contains text that would end the page script early")
        data.append(f'<script type="text/csv" data-dataset="{csv.stem}">\n{text}\n</script>')
    html = (HEAD + "\n".join(data) + "\n" + SHIM + page + "\n" + FOOT).replace("REPO_URL", REPO_URL)
    OUT.write_text(html)
    print(f"Wrote index.html ({len(html) / 1024:.0f} KB, {len(data)} datasets)")


if __name__ == "__main__":
    main()
