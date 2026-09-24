"""Tests der 0-€-Bewertung beigestellter Stücklistenpositionen.

Die Zahlen stammen aus den echten Stücklisten BOM-359-BG.0010-002 (13x
Sonderartikel 9999 beigestellt, mit Unterstückliste BOM-9999-001) und
BOM-1026-BG.0011-005 (nichts beigestellt, darf sich nicht ändern).

Getestet wird die reine Rechenlogik ohne frappe/erpnext — die Override-Klasse
selbst ist ein dünner Aufsatz darauf und braucht eine Bench.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcb_board import beigestellt as b


class Row:
    """Minimaler Ersatz für eine Kindtabellen-Zeile."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def get(self, field, default=None):
        return self.__dict__.get(field, default)


def bom_359_items():
    """Die 27 Positionen aus BOM-359-BG.0010-002, Summe 132,38842 €."""
    rows = [
        ("359-BRD.0006-V1.0", 1, 2.07833, 0),
        ("C.0040", 1, 0.01025, 0), ("C.0043", 17, 0.00596, 0),
        ("C.0185", 1, 0.032, 0), ("C.0191", 1, 0.0127, 0),
        ("C.0453", 1, 0.013064415, 0), ("C.0503", 2, 0.0082, 0),
        ("C.0549", 1, 0.01, 0), ("R.0153", 4, 0.010461409, 0),
        ("R.0397", 1, 0.01156, 0), ("R.0757", 6, 0.009162165, 0),
        ("R.0937", 1, 0.006, 0),
        # beigestellt, Bewertung ohnehin schon 0
        ("WS.0385", 1, 0.0, 1), ("WS.0386", 1, 0.0, 1),
    ]
    items = []
    for code, qty, rate, flag in rows:
        amount = round(rate * qty, 5)
        items.append(Row(item_code=code, qty=qty, rate=rate, base_rate=rate,
                         amount=amount, base_amount=amount,
                         custom_beigestellt=flag, bom_no=""))
    # 13x Sonderartikel 9999, beigestellt, je 10 EUR aus der Unterstückliste
    for _ in range(13):
        items.append(Row(item_code="9999", qty=1, rate=10.0, base_rate=10.0,
                         amount=10.0, base_amount=10.0,
                         custom_beigestellt=1, bom_no="BOM-9999-001"))
    return items


def bom_359_exploded():
    """Explosion: 9999 zusammengefasst auf 13 Stück / 130 €."""
    return [
        Row(item_code="359-BRD.0006-V1.0", stock_qty=1, rate=2.07833, amount=2.07833),
        Row(item_code="9999", stock_qty=13, rate=10.0, amount=130.0),
        Row(item_code="C.0040", stock_qty=1, rate=0.01025, amount=0.01025),
        # WS.0297 stammt aus der Explosion der Unterstückliste und ist dort 0
        Row(item_code="WS.0297", stock_qty=13, rate=0.0, amount=0.0),
    ]


class TestBeigestellt(unittest.TestCase):
    def test_raw_material_cost_faellt_auf_2_39(self):
        """Der Testfall aus dem Auftrag: 132,39 € -> ca. 2,39 €."""
        items = bom_359_items()
        vorher, _ = b.raw_material_totals(items)
        self.assertAlmostEqual(vorher, 132.38842, places=4)

        b.zero_item_rows(items)
        nachher, base_nachher = b.raw_material_totals(items)

        self.assertAlmostEqual(nachher, 2.38842, places=4)
        self.assertAlmostEqual(base_nachher, 2.38842, places=4)
        self.assertAlmostEqual(vorher - nachher, 130.0, places=4)

    def test_alle_13_sonderartikel_stehen_auf_null(self):
        items = bom_359_items()
        b.zero_item_rows(items)
        neuner = [r for r in items if r.item_code == "9999"]
        self.assertEqual(len(neuner), 13)
        for row in neuner:
            self.assertEqual(row.rate, 0.0)
            self.assertEqual(row.base_rate, 0.0)
            self.assertEqual(row.amount, 0.0)
            self.assertEqual(row.base_amount, 0.0)

    def test_nicht_beigestellte_zeilen_bleiben_unveraendert(self):
        items = bom_359_items()
        b.zero_item_rows(items)
        brd = next(r for r in items if r.item_code == "359-BRD.0006-V1.0")
        self.assertAlmostEqual(brd.rate, 2.07833, places=5)
        self.assertAlmostEqual(brd.amount, 2.07833, places=5)

    def test_nur_geaenderte_zeilen_werden_gemeldet(self):
        """WS.0385/0386 sind beigestellt, stehen aber schon auf 0 — die
        brauchen kein db_update und dürfen nicht als geändert gelten."""
        items = bom_359_items()
        changed = b.zero_item_rows(items)
        self.assertEqual({r.item_code for r in changed}, {"9999"})
        self.assertEqual(len(changed), 13)

    def test_explosion_wird_genullt_trotz_unterstueckliste(self):
        """Punkt 3: bom_no darf den Satz nicht zurückholen."""
        items = bom_359_items()
        exploded = bom_359_exploded()
        codes = b.beigestellt_item_codes(items)
        self.assertIn("9999", codes)

        changed = b.zero_exploded_rows(exploded, codes)

        neuner = next(r for r in exploded if r.item_code == "9999")
        self.assertEqual(neuner.rate, 0.0)
        self.assertEqual(neuner.amount, 0.0)
        self.assertEqual([r.item_code for r in changed], ["9999"])
        # Nicht beigestellte Explosionszeilen bleiben stehen
        brd = next(r for r in exploded if r.item_code == "359-BRD.0006-V1.0")
        self.assertAlmostEqual(brd.amount, 2.07833, places=5)

    def test_bom_1026_bleibt_bei_rund_705_euro(self):
        """BOM-1026-BG.0011-005 (300 Stück): bleibt bei ca. 705 € Material.

        Achtung — anders als zunächst angenommen hat auch diese Stückliste
        beigestellte Positionen: 1026-BRD.0011_V1.0 und IC.1128 stehen bereits
        auf 0 €, D.0452 aber auf 0,243 €. Die Materialkosten sinken deshalb um
        genau diesen Betrag von 705,234 € auf 704,991 € — weiterhin „ca. 705 €",
        aber eben nicht unverändert.
        """
        rows = [
            ("1026-BRD.0011_V1.0", 0.0, 1),
            ("C.0145", 0.096, 0), ("C.1126", 1.284, 0), ("C.0560", 87.0, 0),
            ("D.0535", 64.68, 0),
            ("IC.1128", 0.0, 1),
            ("D.0452", 0.243, 1),
            ("R.0636", 4.875, 0), ("XV.1046", 424.644, 0),
            ("L.0324", 104.16, 0), ("R.0725", 2.052, 0), ("R.0876", 16.2, 0),
        ]
        items = [Row(item_code=c, rate=a, base_rate=a, amount=a, base_amount=a,
                     custom_beigestellt=f, bom_no="") for c, a, f in rows]

        vorher, _ = b.raw_material_totals(items)
        self.assertAlmostEqual(vorher, 705.234, places=3)

        changed = b.zero_item_rows(items)
        self.assertEqual([r.item_code for r in changed], ["D.0452"])

        nachher, _ = b.raw_material_totals(items)
        self.assertAlmostEqual(nachher, 704.991, places=3)
        self.assertAlmostEqual(vorher - nachher, 0.243, places=3)
        # Der Auftrag erwartet „ca. 705 €" — das gilt weiterhin.
        self.assertAlmostEqual(nachher, 705.0, delta=0.05)

    def test_bom_ganz_ohne_beigestellte_positionen_bleibt_unberuehrt(self):
        items = [
            Row(item_code="BT.0001", rate=1.5, base_rate=1.5,
                amount=450.0, base_amount=450.0, custom_beigestellt=0, bom_no=""),
            Row(item_code="BT.0002", rate=0.84997, base_rate=0.84997,
                amount=254.991, base_amount=254.991, custom_beigestellt=0, bom_no=""),
        ]
        self.assertEqual(b.zero_item_rows(items), [])
        self.assertEqual(b.beigestellt_item_codes(items), set())
        nachher, _ = b.raw_material_totals(items)
        self.assertAlmostEqual(nachher, 704.991, places=3)

    def test_flag_lesen_funktioniert_fuer_dict_und_objekt(self):
        """Auf Sites ohne das Custom Field darf nichts krachen."""
        self.assertTrue(b.is_beigestellt(Row(custom_beigestellt=1)))
        self.assertFalse(b.is_beigestellt(Row(custom_beigestellt=0)))
        self.assertFalse(b.is_beigestellt(Row(item_code="X")))
        self.assertTrue(b.is_beigestellt({"custom_beigestellt": 1}))
        self.assertFalse(b.is_beigestellt({}))

    def test_leere_codeliste_laesst_explosion_in_ruhe(self):
        exploded = bom_359_exploded()
        self.assertEqual(b.zero_exploded_rows(exploded, set()), [])
        self.assertEqual(exploded[1].amount, 130.0)


if __name__ == "__main__":
    unittest.main()
