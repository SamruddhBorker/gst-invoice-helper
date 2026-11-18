"""GST invoice maths: GSTIN checks, tax split, numbering, amount in words.

All money uses Decimal (never float). Standard library only.

NOT TAX ADVICE. GST rates and rules change. Check current rates and your
obligations with the GST portal or your accountant before relying on this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

CENT = Decimal("0.01")

STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu (legacy)", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}

# Standard GST rates seen on invoices. Rates have changed over time (for example the
# 2025 reform), so this is only a sanity check: an invoice may override it with
# "allowed_rates", and an unknown rate gives an error, never silent acceptance.
DEFAULT_RATES = ("0", "0.1", "0.25", "1", "1.5", "3", "5", "6", "7.5", "12", "18", "28", "40")

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_RE = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")


class InvoiceError(ValueError):
    """Bad invoice input. The message says what to fix."""


# -------------------------------------------------------------------- GSTIN
def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        p = _CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(gstin: str) -> Optional[str]:
    """Return None if the GSTIN looks valid, else a short reason."""
    g = (gstin or "").strip().upper()
    if len(g) != 15:
        return "GSTIN must be 15 characters"
    if not _GSTIN_RE.fullmatch(g):
        return "GSTIN format is wrong"
    if g[:2] not in STATE_CODES:
        return f"unknown state code {g[:2]}"
    if gstin_check_char(g[:14]) != g[14]:
        return "GSTIN check character doesn't match (typo?)"
    return None


# ----------------------------------------------------------------- numbers
def to_decimal(value, what: str) -> Decimal:
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise InvoiceError(f"{what} must be a number, got {value!r}") from None
    if not d.is_finite():
        raise InvoiceError(f"{what} must be a normal number")
    return d


def money(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven",
         "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _under_1000(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(_ONES[n // 100] + " Hundred")
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))
    elif n:
        parts.append(_ONES[n])
    return " ".join(parts)


def int_to_words(n: int) -> str:
    """Indian numbering: thousand, lakh, crore."""
    if n == 0:
        return "Zero"
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(int_to_words(crore) + " Crore")
    if lakh:
        parts.append(_under_1000(lakh) + " Lakh")
    if thousand:
        parts.append(_under_1000(thousand) + " Thousand")
    if n:
        parts.append(_under_1000(n))
    return " ".join(parts)


def amount_in_words(amount: Decimal) -> str:
    amount = money(amount)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    out = "Rupees " + int_to_words(rupees)
    if paise:
        out += " and " + int_to_words(paise) + " Paise"
    return out + " Only"


# ------------------------------------------------------- financial year / no.
def financial_year(d: date) -> str:
    """Indian FY runs 1 April to 31 March. 2026-11-18 -> '26-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def format_number(prefix: str, fy: str, seq: int) -> str:
    """'INV/26-27/0001'. GST rules: at most 16 characters, letters, digits, '/' and '-' only."""
    if not re.fullmatch(r"[A-Za-z0-9-]{1,5}", prefix):
        raise InvoiceError("prefix must be 1-5 letters/digits (so the number fits GST's 16-character limit)")
    number = f"{prefix.upper()}/{fy}/{seq:04d}"
    if len(number) > 16:
        raise InvoiceError(f"invoice number {number} is longer than 16 characters")
    return number


# --------------------------------------------------------------- the invoice
@dataclass
class Line:
    description: str
    hsn: str
    qty: Decimal
    unit: str
    rate: Decimal
    discount: Decimal
    gst_rate: Decimal
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal

    @property
    def total(self) -> Decimal:
        return self.taxable + self.cgst + self.sgst + self.igst


def _text(d: dict, key: str, what: str, lo: int, hi: int, required: bool = True) -> str:
    v = str(d.get(key, "") or "").strip()
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v)
    if required and not v:
        raise InvoiceError(f"{what} is required")
    if len(v) > hi:
        raise InvoiceError(f"{what} is too long (max {hi} characters)")
    return v


def build(data: dict, number: str, inv_date: date) -> dict:
    """Validate input and compute every figure. Returns a plain dict ready to render or store."""
    seller = dict(data.get("seller") or {})
    buyer = dict(data.get("buyer") or {})
    reg = str(seller.get("registration", "regular")).lower()
    if reg not in ("regular", "composition", "unregistered"):
        raise InvoiceError("seller.registration must be regular, composition or unregistered")
    taxable_supplier = reg == "regular"

    s_name = _text(seller, "name", "seller name", 1, 120)
    s_state = str(seller.get("state_code", "")).zfill(2)
    if s_state not in STATE_CODES:
        raise InvoiceError("seller.state_code must be a valid 2-digit GST state code (Goa = 30)")
    s_gstin = str(seller.get("gstin", "") or "").strip().upper()
    if taxable_supplier or reg == "composition":
        err = validate_gstin(s_gstin)
        if err:
            raise InvoiceError(f"seller GSTIN: {err}")
        if s_gstin[:2] != s_state:
            raise InvoiceError("seller GSTIN state code doesn't match seller.state_code")
    elif s_gstin:
        err = validate_gstin(s_gstin)
        if err:
            raise InvoiceError(f"seller GSTIN: {err}")

    b_name = _text(buyer, "name", "buyer name", 1, 120)
    b_gstin = str(buyer.get("gstin", "") or "").strip().upper()
    if b_gstin:
        err = validate_gstin(b_gstin)
        if err:
            raise InvoiceError(f"buyer GSTIN: {err}")
    pos = str(data.get("place_of_supply") or buyer.get("state_code") or (b_gstin[:2] if b_gstin else "")).zfill(2)
    if pos not in STATE_CODES:
        raise InvoiceError("place of supply needed: set buyer.state_code (or place_of_supply) to a GST state code")
    intra = pos == s_state

    allowed = {Decimal(str(r)) for r in data.get("allowed_rates", DEFAULT_RATES)}
    raw_items = data.get("items") or []
    if not raw_items:
        raise InvoiceError("add at least one item")
    if len(raw_items) > 200:
        raise InvoiceError("too many items (max 200)")

    lines: list[Line] = []
    for n, it in enumerate(raw_items, 1):
        where = f"item {n}"
        qty = to_decimal(it.get("qty", 1), f"{where} qty")
        rate = to_decimal(it.get("rate"), f"{where} rate")
        disc = to_decimal(it.get("discount", 0), f"{where} discount")
        if qty <= 0:
            raise InvoiceError(f"{where}: qty must be above 0")
        if rate < 0 or disc < 0:
            raise InvoiceError(f"{where}: rate and discount can't be negative")
        gross = qty * rate
        if disc > gross:
            raise InvoiceError(f"{where}: discount is bigger than the item value")
        hsn = str(it.get("hsn", "") or "").strip()
        if hsn and not re.fullmatch(r"\d{4}|\d{6}|\d{8}", hsn):
            raise InvoiceError(f"{where}: HSN/SAC must be 4, 6 or 8 digits")
        rate_pct = to_decimal(it.get("gst_rate", 0), f"{where} gst_rate") if taxable_supplier else Decimal(0)
        if taxable_supplier and rate_pct not in allowed:
            raise InvoiceError(f"{where}: {rate_pct}% isn't a recognised GST rate; check it, "
                               "or list it in allowed_rates")
        taxable = money(gross - disc)
        cgst = sgst = igst = Decimal(0)
        if intra:
            cgst = sgst = money(taxable * rate_pct / 200)
        else:
            igst = money(taxable * rate_pct / 100)
        lines.append(Line(_text(it, "description", f"{where} description", 1, 200), hsn, qty,
                          _text(it, "unit", f"{where} unit", 0, 10, required=False) or "Nos",
                          rate, disc, rate_pct, taxable, cgst, sgst, igst))

    taxable_total = sum((l.taxable for l in lines), Decimal(0))
    cgst_t = sum((l.cgst for l in lines), Decimal(0))
    sgst_t = sum((l.sgst for l in lines), Decimal(0))
    igst_t = sum((l.igst for l in lines), Decimal(0))
    grand = taxable_total + cgst_t + sgst_t + igst_t
    rounded = grand.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return {
        "number": number, "date": inv_date, "kind": "TAX INVOICE" if taxable_supplier else "BILL OF SUPPLY",
        "registration": reg,
        "seller": {"name": s_name, "gstin": s_gstin, "state_code": s_state,
                   "address": _text(seller, "address", "seller address", 0, 300, required=False),
                   "phone": _text(seller, "phone", "seller phone", 0, 30, required=False),
                   "bank": _text(seller, "bank", "bank details", 0, 300, required=False)},
        "buyer": {"name": b_name, "gstin": b_gstin, "state_code": pos,
                  "address": _text(buyer, "address", "buyer address", 0, 300, required=False)},
        "place_of_supply": pos, "intra_state": intra, "reverse_charge": "No",
        "lines": lines, "taxable": taxable_total, "cgst": cgst_t, "sgst": sgst_t, "igst": igst_t,
        "round_off": rounded - grand, "total": rounded, "words": amount_in_words(rounded),
        "notes": _text(data, "notes", "notes", 0, 500, required=False),
    }
