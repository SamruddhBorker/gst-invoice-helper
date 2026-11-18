#!/usr/bin/env python3
"""gst-invoice-helper: GST invoices for small businesses. Standard library only.

    python invoice.py new examples/intra_state.json            # number it, save it, write HTML
    python invoice.py new examples/inter_state.json --out bill.html
    python invoice.py new draft.json --preview                 # compute only; uses no invoice number
    python invoice.py list --month 2026-11
    python invoice.py summary --month 2026-11 [--csv nov.csv]  # totals by GST rate, B2B vs B2C
    python invoice.py cancel INV/26-27/0003                    # numbers are never reused
    python invoice.py gstin 27AAPFU0939F1ZV                    # check a GSTIN

Open the HTML in a browser and use Print > Save as PDF.
NOT TAX ADVICE: confirm current rates and your obligations with your accountant.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

import gst
import render
from register import Register


def parse_date(s: str | None) -> date:
    if not s:
        return date.today()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise gst.InvoiceError(f"can't read date {s!r}; use YYYY-MM-DD") from None


def load_json(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise gst.InvoiceError(f"can't read {path}: {e}") from None
    if not isinstance(data, dict):
        raise gst.InvoiceError(f"{path} must contain a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # piped output on Windows defaults to cp1252 and can't print ₹
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="invoices.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("file")
    n.add_argument("--prefix", default="INV")
    n.add_argument("--date")
    n.add_argument("--out")
    n.add_argument("--seller", help="JSON file with seller details to merge in")
    n.add_argument("--preview", action="store_true")
    l = sub.add_parser("list")
    l.add_argument("--month")
    s = sub.add_parser("summary")
    s.add_argument("--month", required=True, help="YYYY-MM")
    s.add_argument("--csv")
    sub.add_parser("cancel").add_argument("number")
    sub.add_parser("gstin").add_argument("value")
    args = ap.parse_args(argv)

    if args.cmd == "gstin":
        err = gst.validate_gstin(args.value)
        print("looks valid" if not err else f"not valid: {err}")
        if not err:
            print(f"state: {gst.STATE_CODES[args.value[:2]]}")
        return 0 if not err else 1

    reg = Register(args.db)
    try:
        if args.cmd == "new":
            data = load_json(args.file)
            if args.seller:
                data["seller"] = {**load_json(args.seller), **(data.get("seller") or {})}
            d = parse_date(args.date)
            if args.preview:
                inv = gst.build(data, "PREVIEW", d)
            else:
                inv = reg.issue(data, args.prefix, d)
            out = Path(args.out or (inv["number"].replace("/", "-") + ".html"))
            out.write_text(render.render(inv), encoding="utf-8")
            print(f"{inv['kind']} {inv['number']}  total ₹{inv['total']:,.2f}  ->  {out}")
            print(f"  taxable {inv['taxable']:,.2f}  CGST {inv['cgst']:,.2f}  SGST {inv['sgst']:,.2f}  IGST {inv['igst']:,.2f}"
                  f"  round-off {inv['round_off']:+.2f}")
            print(f"  {inv['words']}")
            if args.preview:
                print("  (preview: nothing saved, no number used)")
        elif args.cmd == "list":
            rows = reg.list(args.month)
            for r in rows:
                flag = "  [CANCELLED]" if r["status"] == "cancelled" else ""
                print(f"{r['number']:<16} {r['date']}  {r['buyer_name'][:28]:<28} ₹{float(r['total']):>12,.2f}{flag}")
            if not rows:
                print("(no invoices)")
        elif args.cmd == "summary":
            sm = reg.summary(args.month)
            print(f"{sm['month']}: {sm['issued']} invoice(s), {sm['cancelled']} cancelled")
            print(f"  B2B (buyer has GSTIN): {sm['b2b']['n']} worth ₹{sm['b2b']['value']:,.2f}")
            print(f"  B2C: {sm['b2c']['n']} worth ₹{sm['b2c']['value']:,.2f}")
            for rate in sorted(sm["by_rate"], key=float):
                b = sm["by_rate"][rate]
                print(f"  {rate:>5}%  taxable ₹{b['taxable']:>12,.2f}  CGST ₹{b['cgst']:>10,.2f}  "
                      f"SGST ₹{b['sgst']:>10,.2f}  IGST ₹{b['igst']:>10,.2f}")
            print(f"  TOTAL   taxable ₹{sm['taxable']:,.2f}  tax ₹{sm['cgst'] + sm['sgst'] + sm['igst']:,.2f}  "
                  f"invoiced ₹{sm['total']:,.2f}")
            print("  This is a summary for your records, not a GST return.")
            if args.csv:
                with open(args.csv, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["number", "date", "buyer", "buyer_gstin", "place_of_supply", "taxable",
                                "cgst", "sgst", "igst", "total", "status"])
                    for r in reg.list(args.month):
                        w.writerow([r["number"], r["date"], _csv_safe(r["buyer_name"]), r["buyer_gstin"],
                                    r["place_of_supply"], r["taxable"], r["cgst"], r["sgst"], r["igst"],
                                    r["total"], r["status"]])
                print(f"  wrote {args.csv}")
        elif args.cmd == "cancel":
            print("cancelled (the number stays used)" if reg.cancel(args.number) else "no such open invoice")
    except (gst.InvoiceError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        reg.close()
    return 0


def _csv_safe(s: str) -> str:
    """Stop spreadsheet formula injection from buyer names like '=HYPERLINK(...)'."""
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


if __name__ == "__main__":
    sys.exit(main())
