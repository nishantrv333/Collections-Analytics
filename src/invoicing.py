"""
Monthly invoices for every bank, in the currency each one is invoiced in.

For each bank it takes the contract in force, the month's billing base from
billing_usage_month, and works out:

  success fee      on money collected in the bank's files dated that month, net of reversals
                   (tiered where the contract says so)
  usage            connected voice minutes and delivered messages, where the contract charges them
  platform fee     prorated in the month a contract starts
  minimum top up   when the month's charges come in under the contract minimum
  corrections      if a month we already invoiced now has a different base (because the data
                   behind it was fixed), the difference goes on this invoice as its own line

Every amount is worked out in the contract currency and converted once, at the end, into the
invoice currency using the last published rate on the last day of the month.

It refuses to write anything if the invoice does not tie back to the warehouse.
Tax is left to finance's accounting tool, so all amounts here are before tax.

Run:  python src/invoicing.py --month 2026-09
"""

import argparse
import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"


@dataclass
class Line:
    client_id: str
    line_type: str
    description: str
    quantity: float
    unit_price: float
    amount: float  # contract currency


def month_bounds(month: str):
    y, m = int(month[:4]), int(month[5:])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def contract_for(contracts: pd.DataFrame, client_id: str, month: str) -> pd.Series:
    first, last = month_bounds(month)
    c = contracts[(contracts.client_id == client_id) & (contracts.valid_from <= last) & (contracts.valid_to >= first)]
    if len(c) != 1:
        # Two contracts inside one month would need the month split by day. Has not happened yet,
        # so I stop rather than guess.
        raise ValueError(f"{client_id} {month}: expected one contract, found {len(c)}")
    return c.iloc[0]


def active_share(contract: pd.Series, month: str) -> float:
    first, last = month_bounds(month)
    start = max(first, contract.valid_from)
    return ((last - start).days + 1) / ((last - first).days + 1)


def success_fee(contract: pd.Series, base: float) -> float:
    if pd.notna(contract.tier_threshold) and base > contract.tier_threshold:
        return contract.success_fee_pct * contract.tier_threshold + contract.success_fee_pct_above * (base - contract.tier_threshold)
    return contract.success_fee_pct * base


def charges(contract: pd.Series, month: str, base: float, minutes: float, messages: float, client_id: str) -> list[Line]:
    lines = []
    if pd.notna(contract.tier_threshold) and base > contract.tier_threshold:
        lines.append(Line(client_id, "success_fee", f"Success fee {contract.success_fee_pct:.0%} up to {contract.tier_threshold:,.0f}",
                          contract.tier_threshold, contract.success_fee_pct, contract.success_fee_pct * contract.tier_threshold))
        above = base - contract.tier_threshold
        lines.append(Line(client_id, "success_fee", f"Success fee {contract.success_fee_pct_above:.0%} above {contract.tier_threshold:,.0f}",
                          above, contract.success_fee_pct_above, contract.success_fee_pct_above * above))
    else:
        lines.append(Line(client_id, "success_fee", f"Success fee {contract.success_fee_pct:.0%} of net collected",
                          base, contract.success_fee_pct, contract.success_fee_pct * base))
    if contract.fee_per_voice_minute:
        lines.append(Line(client_id, "voice_minutes", "Connected voice minutes", minutes, contract.fee_per_voice_minute,
                          minutes * contract.fee_per_voice_minute))
    if contract.fee_per_message:
        lines.append(Line(client_id, "messages", "Messages delivered (WhatsApp, SMS, email)", messages, contract.fee_per_message,
                          messages * contract.fee_per_message))
    if contract.platform_fee_monthly:
        share = active_share(contract, month)
        desc = "Platform fee" if share == 1 else f"Platform fee, {share:.0%} of month (contract started {contract.valid_from:%d %b})"
        lines.append(Line(client_id, "platform_fee", desc, share, contract.platform_fee_monthly, contract.platform_fee_monthly * share))
    subtotal = sum(l.amount for l in lines)
    minimum = contract.monthly_minimum * active_share(contract, month)
    if minimum and subtotal < minimum:
        lines.append(Line(client_id, "minimum_top_up", f"Top up to monthly minimum of {minimum:,.2f}", 1, minimum - subtotal, minimum - subtotal))
    for l in lines:
        l.amount = round(l.amount, 2)
    return lines


def rate_on(fx: pd.DataFrame, currency: str, day: date) -> float:
    if currency == "EUR":
        return 1.0
    r = fx[(fx.currency == currency) & (fx.rate_date <= day)].sort_values("rate_date")
    return float(r.iloc[-1].units_per_eur)


def write_pdf(path: Path, inv: dict, lines: pd.DataFrame):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm)
    cur = inv["invoice_currency"]
    story = [
        Paragraph("Sample invoice built from synthetic data", styles["Italic"]),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Invoice {inv['invoice_number']}</b>", styles["Title"]),
        Paragraph(f"Bill to: <b>{inv['client_name']}</b><br/>Period: {inv['period_label']}<br/>"
                  f"Contract: {inv['contract_id']}<br/>Invoice currency: {cur}", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    rows = [["Description", "Quantity", "Unit price", f"Amount ({inv['contract_currency']})"]]
    for _, l in lines.iterrows():
        unit = f"{l.unit_price:.0%}" if l.line_type == "success_fee" else f"{l.unit_price:,.4f}".rstrip("0").rstrip(".")
        rows.append([Paragraph(l.description, styles["Normal"]), f"{l.quantity:,.2f}", unit, f"{l.amount:,.2f}"])
    rows.append(["", "", "Total", f"{inv['total_contract_currency']:,.2f}"])
    t = Table(rows, colWidths=[88 * mm, 28 * mm, 26 * mm, 32 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f4f4f4")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    if cur != inv["contract_currency"]:
        story += [Spacer(1, 4 * mm), Paragraph(
            f"Converted to {cur} at {inv['fx_rate']:.6f} {cur} per {inv['contract_currency']} "
            f"(last published rate on or before {inv['fx_date']}).", styles["Normal"])]
    story += [Spacer(1, 4 * mm), Paragraph(f"<b>Total due: {cur} {inv['total_invoice_currency']:,.2f}</b> (before tax)", styles["Heading3"]),
              Paragraph(f"The success fee base is the sum of the {inv['bank_files']} payment files you sent us dated in this period. "
                        "The file by file list is attached as a CSV so every line can be checked against your own records.",
                        styles["Normal"])]
    doc.build(story)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="2026-09")
    month = ap.parse_args().month
    first, last = month_bounds(month)
    out = ROOT / "output" / "invoices" / month
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB), read_only=True)
    contracts = con.execute("select * from stg_contracts").df()
    for col in ("valid_from", "valid_to"):
        contracts[col] = pd.to_datetime(contracts[col]).dt.date
    usage = con.execute("select * from billing_usage_month").df()
    clients = con.execute("select * from stg_clients").df().set_index("client_id")
    issued = con.execute("select * from stg_invoices_issued").df()
    fx = con.execute("select rate_date, currency, units_per_eur from int_fx_daily").df()
    fx["rate_date"] = pd.to_datetime(fx["rate_date"]).dt.date
    files = con.execute("""
        select client_id, source_file, file_date, count(*) as rows,
               sum(amount) filter (where payment_type = 'payment') as payments,
               coalesce(sum(amount) filter (where payment_type = 'reversal'), 0) as reversals,
               sum(amount) as net
        from int_payments where billing_month = ? group by 1, 2, 3 order by 1, 3""", [month]).df()
    con.close()

    all_lines, invoices = [], []
    for client_id, u in usage[usage.billing_month == month].set_index("client_id").iterrows():
        contract = contract_for(contracts, client_id, month)
        lines = charges(contract, month, float(u.net_collected), float(u.billable_minutes), float(u.messages_delivered), client_id)

        # corrections to months already invoiced
        for _, prev in issued[(issued.client_id == client_id) & (issued.billing_month < month)].iterrows():
            pu = usage[(usage.client_id == client_id) & (usage.billing_month == prev.billing_month)].iloc[0]
            pc = contract_for(contracts, client_id, prev.billing_month)
            billed = sum(l.amount for l in charges(pc, prev.billing_month, float(prev.billed_collected_base),
                                                      float(pu.billable_minutes), float(pu.messages_delivered), client_id))
            correct = sum(l.amount for l in charges(pc, prev.billing_month, float(pu.net_collected),
                                                       float(pu.billable_minutes), float(pu.messages_delivered), client_id))
            diff = round(correct - billed, 2)
            if abs(diff) >= 0.01:
                gap = abs(float(pu.net_collected) - float(prev.billed_collected_base))
                lines.append(Line(client_id, "correction",
                                  f"Correction to {prev.invoice_number}: we billed on {float(prev.billed_collected_base):,.2f}, "
                                  f"the right base is {float(pu.net_collected):,.2f}. The {gap:,.2f} difference was payments "
                                  f"from one bank file that loaded twice.",
                                  1, diff, diff))

        cc, ic = contract.contract_currency, contract.invoice_currency
        rate = rate_on(fx, ic, last) / rate_on(fx, cc, last)
        total_cc = round(sum(l.amount for l in lines), 2)
        inv = dict(invoice_number=f"INV-{month.replace('-', '')}-{client_id}", client_id=client_id,
                   client_name=clients.loc[client_id, "client_name"], billing_month=month,
                   period_label=f"{first.day} {first:%B %Y} to {last.day} {last:%B %Y}", contract_id=contract.contract_id,
                   contract_currency=cc, invoice_currency=ic, fx_rate=rate, fx_date=str(last),
                   success_fee_base=float(u.net_collected), bank_files=int(u.bank_files),
                   total_contract_currency=total_cc, total_invoice_currency=round(total_cc * rate, 2),
                   total_eur=round(total_cc / rate_on(fx, cc, last), 2))
        invoices.append(inv)
        lf = pd.DataFrame([l.__dict__ for l in lines])
        lf.insert(0, "invoice_number", inv["invoice_number"])
        lf["amount_invoice_currency"] = (lf.amount * rate).round(2)
        all_lines.append(lf)

        # reconciliation: refuse to write an invoice that does not tie back to the data
        fee_base = sum(l.quantity for l in lines if l.line_type == "success_fee")
        file_total = float(files[files.client_id == client_id].net.sum())
        assert abs(fee_base - float(u.net_collected)) < 0.01, f"{client_id}: success fee base does not match warehouse"
        assert abs(file_total - float(u.net_collected)) < 0.01, f"{client_id}: bank files do not add up to billing base"
        assert abs(lf.amount.sum() - total_cc) < 0.01, f"{client_id}: lines do not add up to total"

        write_pdf(out / f"{inv['invoice_number']}.pdf", inv, lf)
        files[files.client_id == client_id].to_csv(out / f"{inv['invoice_number']}_bank_files.csv", index=False)

    summary = pd.DataFrame(invoices)
    lines_df = pd.concat(all_lines, ignore_index=True)
    summary.to_csv(out / "invoice_summary.csv", index=False)
    lines_df.to_csv(out / "invoice_lines.csv", index=False)

    print(f"Invoices for {month}:")
    for _, i in summary.iterrows():
        print(f"  {i.invoice_number}  {i.client_name:<16}{i.invoice_currency} {i.total_invoice_currency:>14,.2f}   (EUR {i.total_eur:>12,.2f})")
    print(f"  Total in EUR: {summary.total_eur.sum():,.2f}")
    corr = lines_df[lines_df.line_type == "correction"]
    for _, c in corr.iterrows():
        print(f"  Correction on {c.invoice_number}: {c.amount:,.2f}. {c.description}")
    print(f"Written to {out.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
