"""Invoice register (SQLite): consecutive numbering per financial year, cancellation, monthly summary."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Optional

import gst

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  number TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL,
  fy TEXT NOT NULL,
  seq INTEGER NOT NULL,
  date TEXT NOT NULL,
  buyer_name TEXT NOT NULL,
  buyer_gstin TEXT NOT NULL DEFAULT '',
  place_of_supply TEXT NOT NULL,
  kind TEXT NOT NULL,
  taxable TEXT NOT NULL, cgst TEXT NOT NULL, sgst TEXT NOT NULL, igst TEXT NOT NULL, total TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'issued',        -- issued | cancelled (numbers are never reused)
  lines TEXT NOT NULL,
  UNIQUE(prefix, fy, seq)
);
"""


def _lines_json(inv: dict) -> str:
    return json.dumps([{k: str(v) for k, v in asdict(l).items()} for l in inv["lines"]])


class Register:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def issue(self, data: dict, prefix: str, inv_date: date) -> dict:
        """Validate, number and save an invoice in one transaction.

        The number is only consumed when the invoice is valid, so there are no gaps from typos.
        """
        fy = gst.financial_year(inv_date)
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute("SELECT COALESCE(MAX(seq),0) FROM invoices WHERE prefix=? AND fy=?",
                                      (prefix.upper(), fy)).fetchone()
                seq = row[0] + 1
                number = gst.format_number(prefix, fy, seq)
                inv = gst.build(data, number, inv_date)
                self.db.execute(
                    "INSERT INTO invoices(number,prefix,fy,seq,date,buyer_name,buyer_gstin,place_of_supply,kind,"
                    "taxable,cgst,sgst,igst,total,lines) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (number, prefix.upper(), fy, seq, inv_date.isoformat(), inv["buyer"]["name"],
                     inv["buyer"]["gstin"], inv["place_of_supply"], inv["kind"], str(inv["taxable"]),
                     str(inv["cgst"]), str(inv["sgst"]), str(inv["igst"]), str(inv["total"]), _lines_json(inv)))
                self.db.execute("COMMIT")
                return inv
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def cancel(self, number: str) -> bool:
        with self.lock:
            return self.db.execute("UPDATE invoices SET status='cancelled' WHERE number=? AND status='issued'",
                                   (number,)).rowcount == 1

    def list(self, month: Optional[str] = None) -> list[sqlite3.Row]:
        with self.lock:
            if month:
                return self.db.execute("SELECT * FROM invoices WHERE date LIKE ? ORDER BY date, id",
                                       (month + "-%",)).fetchall()
            return self.db.execute("SELECT * FROM invoices ORDER BY date, id").fetchall()

    def summary(self, month: str) -> dict:
        """Totals for the month, excluding cancelled invoices. Not a GSTR-1 filing."""
        rows = self.list(month)
        out = {"month": month, "issued": 0, "cancelled": 0, "b2b": {"n": 0, "value": Decimal(0)},
               "b2c": {"n": 0, "value": Decimal(0)}, "by_rate": {},
               "taxable": Decimal(0), "cgst": Decimal(0), "sgst": Decimal(0), "igst": Decimal(0),
               "total": Decimal(0)}
        for r in rows:
            if r["status"] == "cancelled":
                out["cancelled"] += 1
                continue
            out["issued"] += 1
            for k in ("taxable", "cgst", "sgst", "igst", "total"):
                out[k] += Decimal(r[k])
            bucket = out["b2b"] if r["buyer_gstin"] else out["b2c"]
            bucket["n"] += 1
            bucket["value"] += Decimal(r["total"])
            for l in json.loads(r["lines"]):
                rate = Decimal(l["gst_rate"]).normalize()
                b = out["by_rate"].setdefault(f"{rate:f}", {k: Decimal(0) for k in ("taxable", "cgst", "sgst", "igst")})
                for k in b:
                    b[k] += Decimal(l[k])
        return out
