"""Printable HTML invoice (one self-contained file). Every value is HTML-escaped."""
from __future__ import annotations

from decimal import Decimal
from html import escape

from gst import STATE_CODES

CSS = """
@page{size:A4;margin:12mm}
body{font:13px/1.4 system-ui,Arial,sans-serif;color:#111;margin:0;padding:16px}
.wrap{max-width:900px;margin:auto}
h1{font-size:20px;margin:0;text-align:center;letter-spacing:.08em}
.sub{text-align:center;color:#555;margin-bottom:10px}
.box{border:1px solid #999;padding:8px 10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
.grid .box+.box{border-left:0}
table{border-collapse:collapse;width:100%;margin-top:8px}
th,td{border:1px solid #999;padding:4px 6px;text-align:left;vertical-align:top}
th{background:#f1f1f1}
.n{text-align:right;white-space:nowrap}
.tot td{font-weight:600}
.words{margin-top:8px}
.foot{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px}
.sign{text-align:right;margin-top:40px}
.muted{color:#555;font-size:12px}
"""


def _m(d: Decimal) -> str:
    return f"{d:,.2f}"


def _party(label: str, p: dict) -> str:
    state = STATE_CODES.get(p["state_code"], "")
    lines = [f"<b>{escape(p['name'])}</b>"]
    if p.get("address"):
        lines.append(escape(p["address"]).replace("\n", "<br>"))
    if p.get("gstin"):
        lines.append(f"GSTIN: {escape(p['gstin'])}")
    lines.append(f"State: {escape(state)} ({escape(p['state_code'])})")
    if p.get("phone"):
        lines.append(f"Phone: {escape(p['phone'])}")
    return f'<div class="box"><div class="muted">{escape(label)}</div>{"<br>".join(lines)}</div>'


def render(inv: dict, currency: str = "₹") -> str:
    tax = inv["kind"] == "TAX INVOICE"
    intra = inv["intra_state"]
    head = ["#", "Description", "HSN/SAC", "Qty", "Rate", "Disc.", "Taxable value"]
    if tax:
        head += ["CGST %", "CGST", "SGST %", "SGST"] if intra else ["IGST %", "IGST"]
    head.append("Amount")
    rows = []
    for i, l in enumerate(inv["lines"], 1):
        cells = [str(i), escape(l.description), escape(l.hsn or "-"), f"{l.qty.normalize():f} {escape(l.unit)}",
                 _m(l.rate), _m(l.discount) if l.discount else "-", _m(l.taxable)]
        if tax:
            half = (l.gst_rate / 2).normalize()
            cells += ([f"{half:f}", _m(l.cgst), f"{half:f}", _m(l.sgst)] if intra
                      else [f"{l.gst_rate.normalize():f}", _m(l.igst)])
        cells.append(_m(l.total))
        rows.append("<tr>" + "".join(f'<td class="{"n" if j >= 3 else ""}">{c}</td>' for j, c in enumerate(cells)) + "</tr>")

    totals = [("Taxable value", inv["taxable"])]
    if tax:
        totals += [("CGST", inv["cgst"]), ("SGST", inv["sgst"])] if intra else [("IGST", inv["igst"])]
    if inv["round_off"]:
        totals.append(("Round off", inv["round_off"]))
    totals.append((f"Total ({currency})", inv["total"]))
    trs = "".join(f'<tr class="{"tot" if k.startswith("Total") else ""}"><td>{escape(k)}</td><td class="n">{_m(v)}</td></tr>'
                  for k, v in totals)

    declaration = ("Composition taxable person, not eligible to collect tax on supplies."
                   if inv["registration"] == "composition" else
                   "Supplier is not registered under GST, no tax charged." if not tax else
                   "We declare that this invoice shows the actual price of the goods/services and that all particulars are true and correct.")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(inv['kind'].title())} {escape(inv['number'])}</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>{escape(inv['kind'])}</h1>
<div class="sub">Invoice No: <b>{escape(inv['number'])}</b> &nbsp;|&nbsp; Date: <b>{inv['date'].strftime('%d-%m-%Y')}</b>
 &nbsp;|&nbsp; Reverse charge: {escape(inv['reverse_charge'])}</div>
<div class="grid">{_party('Supplier', {**inv['seller']})}{_party('Bill to', inv['buyer'])}</div>
<div class="box" style="margin-top:-1px">Place of supply: <b>{escape(STATE_CODES.get(inv['place_of_supply'], ''))} ({escape(inv['place_of_supply'])})</b>
 &nbsp;|&nbsp; {'Intra-state: CGST + SGST' if intra else 'Inter-state: IGST'}</div>
<table><thead><tr>{''.join(f'<th>{escape(h)}</th>' for h in head)}</tr></thead><tbody>{''.join(rows)}</tbody></table>
<div class="foot"><div>
<div class="words"><b>Amount in words:</b> {escape(inv['words'])}</div>
{f'<div class="words"><b>Notes:</b> {escape(inv["notes"])}</div>' if inv['notes'] else ''}
{f'<div class="words"><b>Bank details:</b> {escape(inv["seller"]["bank"])}</div>' if inv['seller']['bank'] else ''}
<div class="muted words">{escape(declaration)}</div></div>
<div><table>{trs}</table>
<div class="sign">For {escape(inv['seller']['name'])}<br><br><br>Authorised signatory</div></div></div>
</div></body></html>
"""
