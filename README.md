# gst-invoice-helper

[![tests](https://github.com/SamruddhBorker/gst-invoice-helper/actions/workflows/tests.yml/badge.svg)](https://github.com/SamruddhBorker/gst-invoice-helper/actions/workflows/tests.yml)

GST-ready invoices for tiny shops, cafés and freelancers in India. Write the sale
as a small JSON file and get a printable invoice with the correct CGST/SGST or
IGST split, consecutive numbering, round-off and the amount in words. It also
keeps a register and gives you a monthly summary by GST rate.

**The problem:** small businesses still do invoices and GST by hand in Word or
Excel. That leads to wrong tax splits, duplicate or missing invoice numbers, and
a scramble at month end.

- Python 3.9+, **standard library only**, SQLite register
- Uses exact `Decimal` arithmetic: no floating-point rounding errors
- Output is a clean HTML invoice: open it in a browser and *Print → Save as PDF*

> **Not tax advice.** GST rates and rules change (for example the 2025 rate reform).
> Always check current rates and your obligations with the GST portal or your
> accountant. This tool does the arithmetic and bookkeeping; it does not decide
> what rate applies to your goods.

## Quick start

```bash
python invoice.py new examples/intra_state.json     # Goa seller, Goa buyer: CGST + SGST
python invoice.py new examples/inter_state.json     # Goa seller, Maharashtra buyer: IGST
python invoice.py new draft.json --preview          # check the maths without using a number
python invoice.py list --month 2026-11
python invoice.py summary --month 2026-11 --csv nov.csv
python invoice.py cancel INV/26-27/0003
python invoice.py gstin 27AAPFU0939F1ZV             # validate a GSTIN
```

Copy an example, edit the details, run `new`. The sample GSTINs and bank details are fictional.

## What it handles

- **CGST + SGST vs IGST** from the seller's state and the place of supply (Goa is state code 30)
- **GSTIN validation**: format, state code and the check character, so typos are caught before you issue the invoice
- **Invoice numbers**: `INV/26-27/0001`. Consecutive per financial year (April to March), at most 16 characters as GST requires, restarting each April. A failed or invalid invoice doesn't use up a number, and cancelled numbers are never reused
- **Discounts, HSN/SAC codes, units, notes, bank details**
- **Round-off** to the nearest rupee, shown as its own line
- **Amount in words** in Indian style (lakh, crore)
- **Bill of Supply** automatically for composition and unregistered sellers (no tax charged)
- **Monthly summary** by GST rate, B2B vs B2C, with a CSV register (formula-injection safe)

## Input format

```json
{
  "seller": { "name": "...", "gstin": "30AAACP1234C1ZE", "state_code": "30", "registration": "regular" },
  "buyer":  { "name": "...", "gstin": "(optional)", "state_code": "27" },
  "items": [
    { "description": "Coffee beans", "hsn": "0901", "qty": 2, "unit": "Kg", "rate": 850.5, "gst_rate": 5, "discount": 50 }
  ]
}
```

Rates are *before tax*. `registration` is `regular`, `composition` or `unregistered`.
If a buyer has no GSTIN, set `buyer.state_code` (the place of supply). Put your
seller details in a `seller.json` once and pass `--seller seller.json`.

## Known limits (please read)

- **Not a GST return.** The summary is for your records. It doesn't produce GSTR-1/3B files
- **No e-invoicing/IRN or QR code.** Businesses above the government's turnover threshold must generate those through the e-invoice portal
- Tax is calculated per line and summed, which the rules allow, but check against your accountant's method
- Place of supply for services and special cases (for example hotels, transport, imports) can differ; set `place_of_supply` yourself when it does
- Rates are validated against a list of standard rates only as a typo guard. If a rate is missing, add it with `allowed_rates`. Whether a rate applies to your item is your call
- One currency (₹), one seller per database

## Layout

| File | Role |
|---|---|
| `invoice.py` | command-line interface |
| `gst.py` | GSTIN checks, tax maths, numbering, amount in words |
| `register.py` | SQLite register, atomic numbering, summary |
| `render.py` | printable HTML invoice (everything escaped) |
| `examples/` | sample invoices |

## Tests

```bash
python -m unittest -v
```

The tests include hand-checked figures (for example ₹16,975 with a −₹0.48 round-off)
and a published sample GSTIN for the checksum.

## License

MIT
