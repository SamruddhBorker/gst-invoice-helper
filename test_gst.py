import copy
import csv
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import gst
import invoice
import render
from register import Register

HERE = Path(__file__).parent
INTRA = json.loads((HERE / "examples" / "intra_state.json").read_text(encoding="utf-8"))
INTER = json.loads((HERE / "examples" / "inter_state.json").read_text(encoding="utf-8"))
D = date(2026, 11, 18)


def build(data, number="INV/26-27/0001", d=D):
    return gst.build(copy.deepcopy(data), number, d)


class GstinTests(unittest.TestCase):
    def test_known_sample_gstin_is_valid(self):
        self.assertIsNone(gst.validate_gstin("27AAPFU0939F1ZV"))

    def test_typo_is_caught_by_check_character(self):
        self.assertIn("check", gst.validate_gstin("27AAPFU0939F1ZW"))

    def test_format_errors(self):
        self.assertIn("15", gst.validate_gstin("123"))
        self.assertIn("format", gst.validate_gstin("27aapfu0939f1zv"[:14] + "!"))
        self.assertIn("state", gst.validate_gstin("00AAPFU0939F1Z" + gst.gstin_check_char("00AAPFU0939F1Z")))

    def test_goa_is_30(self):
        self.assertEqual(gst.STATE_CODES["30"], "Goa")


class WordsTests(unittest.TestCase):
    def test_words(self):
        w = gst.amount_in_words
        self.assertEqual(w(Decimal("0")), "Rupees Zero Only")
        self.assertEqual(w(Decimal("100000")), "Rupees One Lakh Only")
        self.assertEqual(w(Decimal("123456.50")),
                         "Rupees One Lakh Twenty Three Thousand Four Hundred Fifty Six and Fifty Paise Only")
        self.assertEqual(w(Decimal("10000000")), "Rupees One Crore Only")
        self.assertEqual(w(Decimal("1000000000")), "Rupees One Hundred Crore Only")
        self.assertEqual(w(Decimal("19")), "Rupees Nineteen Only")
        self.assertEqual(w(Decimal("101")), "Rupees One Hundred One Only")


class NumberingTests(unittest.TestCase):
    def test_financial_year_boundaries(self):
        self.assertEqual(gst.financial_year(date(2027, 3, 31)), "26-27")
        self.assertEqual(gst.financial_year(date(2027, 4, 1)), "27-28")
        self.assertEqual(gst.financial_year(date(2026, 1, 15)), "25-26")

    def test_number_format_and_limits(self):
        self.assertEqual(gst.format_number("inv", "26-27", 7), "INV/26-27/0007")
        with self.assertRaises(gst.InvoiceError):
            gst.format_number("TOOLONG", "26-27", 1)
        with self.assertRaises(gst.InvoiceError):
            gst.format_number("IN/V", "26-27", 1)
        self.assertLessEqual(len(gst.format_number("ABCDE", "26-27", 9999)), 16)


class TaxMathTests(unittest.TestCase):
    def test_intra_state_splits_cgst_sgst(self):
        inv = build(INTRA)
        self.assertTrue(inv["intra_state"])
        self.assertEqual(inv["taxable"], Decimal("15945.00"))
        self.assertEqual(inv["cgst"], Decimal("515.24"))
        self.assertEqual(inv["sgst"], Decimal("515.24"))
        self.assertEqual(inv["igst"], Decimal("0"))
        self.assertEqual(inv["round_off"], Decimal("-0.48"))
        self.assertEqual(inv["total"], Decimal("16975"))
        self.assertEqual(inv["words"], "Rupees Sixteen Thousand Nine Hundred Seventy Five Only")

    def test_half_paise_rounds_up(self):
        # 1651 x 5% / 2 = 41.275 -> 41.28
        self.assertEqual(build(INTRA)["lines"][1].cgst, Decimal("41.28"))

    def test_inter_state_uses_igst(self):
        inv = build(INTER)
        self.assertFalse(inv["intra_state"])
        self.assertEqual(inv["place_of_supply"], "27")
        self.assertEqual((inv["cgst"], inv["sgst"], inv["igst"]), (0, 0, Decimal("3870.00")))
        self.assertEqual(inv["total"], Decimal("77370"))

    def test_decimal_precision_no_float_drift(self):
        data = copy.deepcopy(INTRA)
        data["items"] = [{"description": "x", "qty": 3, "rate": 0.1, "gst_rate": 0}]
        self.assertEqual(build(data)["taxable"], Decimal("0.30"))

    def test_composition_dealer_charges_no_tax(self):
        data = copy.deepcopy(INTRA)
        data["seller"]["registration"] = "composition"
        inv = build(data)
        self.assertEqual(inv["kind"], "BILL OF SUPPLY")
        self.assertEqual((inv["cgst"], inv["sgst"], inv["igst"]), (0, 0, 0))
        self.assertEqual(inv["total"], Decimal("15945"))

    def test_unregistered_seller_needs_no_gstin(self):
        data = copy.deepcopy(INTRA)
        data["seller"].update(registration="unregistered", gstin="")
        self.assertEqual(build(data)["kind"], "BILL OF SUPPLY")


class ValidationTests(unittest.TestCase):
    def bad(self, mutate, expect):
        data = copy.deepcopy(INTRA)
        mutate(data)
        with self.assertRaises(gst.InvoiceError) as cm:
            build(data)
        self.assertIn(expect, str(cm.exception))

    def test_rejects_unknown_rate(self):
        self.bad(lambda d: d["items"][0].update(gst_rate=15), "recognised GST rate")

    def test_allowed_rates_override(self):
        data = copy.deepcopy(INTRA)
        data["items"][0]["gst_rate"] = 15
        data["allowed_rates"] = [0, 5, 15, 18]
        self.assertEqual(build(data)["lines"][0].gst_rate, Decimal("15"))

    def test_seller_gstin_checks(self):
        self.bad(lambda d: d["seller"].update(gstin="30AAACP1234C1ZX"), "seller GSTIN")
        self.bad(lambda d: d["seller"].update(state_code="27"), "doesn't match")

    def test_buyer_gstin_checked(self):
        self.bad(lambda d: d["buyer"].update(gstin="27AAPFU0939F1ZW"), "buyer GSTIN")

    def test_item_checks(self):
        self.bad(lambda d: d["items"][0].update(qty=0), "qty")
        self.bad(lambda d: d["items"][0].update(rate=-5), "negative")
        self.bad(lambda d: d["items"][0].update(discount=10**9), "discount")
        self.bad(lambda d: d["items"][0].update(hsn="12"), "HSN")
        self.bad(lambda d: d["items"][0].update(rate="abc"), "number")
        self.bad(lambda d: d["items"][0].update(rate="NaN"), "normal number")
        self.bad(lambda d: d["items"][0].pop("description"), "description")
        self.bad(lambda d: d.update(items=[]), "at least one item")

    def test_place_of_supply_required(self):
        self.bad(lambda d: d["buyer"].pop("state_code"), "place of supply")

    def test_html_is_escaped(self):
        data = copy.deepcopy(INTRA)
        data["buyer"]["name"] = "<script>alert(1)</script>"
        data["items"][0]["description"] = "<img src=x onerror=alert(1)>"
        html = render.render(build(data))
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_shows_correct_tax_columns(self):
        self.assertIn("CGST", render.render(build(INTRA)))
        self.assertNotIn("IGST", render.render(build(INTRA)).split("<tbody>")[0])
        self.assertIn("IGST", render.render(build(INTER)))
        self.assertIn("BILL OF SUPPLY", render.render(build({**INTRA, "seller": {**INTRA["seller"], "registration": "composition"}})))


class RegisterTests(unittest.TestCase):
    def test_consecutive_numbers_and_no_gaps_on_failure(self):
        r = Register()
        self.assertEqual(r.issue(copy.deepcopy(INTRA), "INV", D)["number"], "INV/26-27/0001")
        broken = copy.deepcopy(INTRA)
        broken["items"][0]["gst_rate"] = 99
        with self.assertRaises(gst.InvoiceError):
            r.issue(broken, "INV", D)
        self.assertEqual(r.issue(copy.deepcopy(INTER), "INV", D)["number"], "INV/26-27/0002")

    def test_new_financial_year_restarts_and_prefixes_are_separate(self):
        r = Register()
        r.issue(copy.deepcopy(INTRA), "INV", date(2027, 3, 31))
        self.assertEqual(r.issue(copy.deepcopy(INTRA), "INV", date(2027, 4, 1))["number"], "INV/27-28/0001")
        self.assertEqual(r.issue(copy.deepcopy(INTRA), "TAX", date(2027, 4, 1))["number"], "TAX/27-28/0001")

    def test_cancelled_number_is_not_reused(self):
        r = Register()
        n1 = r.issue(copy.deepcopy(INTRA), "INV", D)["number"]
        self.assertTrue(r.cancel(n1))
        self.assertFalse(r.cancel(n1))
        self.assertEqual(r.issue(copy.deepcopy(INTRA), "INV", D)["number"], "INV/26-27/0002")

    def test_summary_by_rate_and_b2b_split(self):
        r = Register()
        r.issue(copy.deepcopy(INTRA), "INV", D)     # B2C intra
        n2 = r.issue(copy.deepcopy(INTER), "INV", D)["number"]   # B2B inter
        sm = r.summary("2026-11")
        self.assertEqual((sm["issued"], sm["b2b"]["n"], sm["b2c"]["n"]), (2, 1, 1))
        self.assertEqual(sm["by_rate"]["5"]["taxable"], Decimal("86151.00"))
        self.assertEqual(sm["by_rate"]["5"]["cgst"], Decimal("353.78"))
        self.assertEqual(sm["by_rate"]["5"]["igst"], Decimal("3600.00"))
        self.assertEqual(sm["by_rate"]["18"]["taxable"], Decimal("3294.00"))
        self.assertEqual(sm["total"], Decimal("16975") + Decimal("77370"))
        r.cancel(n2)
        sm = r.summary("2026-11")
        self.assertEqual((sm["issued"], sm["cancelled"]), (1, 1))
        self.assertEqual(sm["total"], Decimal("16975"))
        self.assertEqual(r.summary("2026-12")["issued"], 0)


class CliTests(unittest.TestCase):
    def test_new_list_summary_cancel(self):
        with tempfile.TemporaryDirectory() as t:
            db, out = str(Path(t) / "i.db"), str(Path(t) / "o.html")
            base = ["--db", db]
            self.assertEqual(invoice.main(base + ["new", str(HERE / "examples/intra_state.json"),
                                                  "--date", "2026-11-18", "--out", out]), 0)
            self.assertIn("TAX INVOICE", Path(out).read_text(encoding="utf-8"))
            self.assertEqual(invoice.main(base + ["new", str(HERE / "examples/inter_state.json"),
                                                  "--date", "2026-11-18", "--preview", "--out", out]), 0)
            # preview used no number: the next real invoice is still #2
            self.assertEqual(invoice.main(base + ["new", str(HERE / "examples/inter_state.json"),
                                                  "--date", "2026-11-19", "--out", out]), 0)
            self.assertIn("INV/26-27/0002", Path(out).read_text(encoding="utf-8"))
            self.assertEqual(invoice.main(base + ["list", "--month", "2026-11"]), 0)
            csv_path = Path(t) / "s.csv"
            self.assertEqual(invoice.main(base + ["summary", "--month", "2026-11", "--csv", str(csv_path)]), 0)
            with open(csv_path, newline="", encoding="utf-8") as f:
                self.assertEqual(len(list(csv.reader(f))), 3)   # header + 2
            self.assertEqual(invoice.main(base + ["cancel", "INV/26-27/0002"]), 0)

    def test_errors_return_1(self):
        with tempfile.TemporaryDirectory() as t:
            base = ["--db", str(Path(t) / "i.db")]
            self.assertEqual(invoice.main(base + ["new", str(Path(t) / "missing.json")]), 1)
            bad = Path(t) / "bad.json"
            bad.write_text("[1,2]", encoding="utf-8")
            self.assertEqual(invoice.main(base + ["new", str(bad)]), 1)
            self.assertEqual(invoice.main(base + ["new", str(HERE / "examples/intra_state.json"),
                                                  "--date", "yesterday"]), 1)

    def test_gstin_command(self):
        self.assertEqual(invoice.main(["gstin", "27AAPFU0939F1ZV"]), 0)
        self.assertEqual(invoice.main(["gstin", "27AAPFU0939F1ZW"]), 1)

    def test_csv_formula_injection_neutralised(self):
        self.assertEqual(invoice._csv_safe('=HYPERLINK("http://x")'), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(invoice._csv_safe("+1"), "'+1")
        self.assertEqual(invoice._csv_safe("Normal Name"), "Normal Name")


if __name__ == "__main__":
    unittest.main()
