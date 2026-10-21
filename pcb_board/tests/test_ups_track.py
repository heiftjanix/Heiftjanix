"""Zustellermittlung: UPS-Auskunft, Schätzung und eingescannter Lieferschein.

Kern der Tests ist die Rangfolge der Quellen. Der Scan ersetzt die Schätzung,
aber nicht die Live-Auskunft von UPS — und er darf auf keinen Fall mit dem
UPS-Versandlabel verwechselt werden, das schon beim Verpacken am Vorgang hängt.
"""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcb_board import ups_track

CONFIG = {
    "billing": {"ups_transit_days": 2},
    "holidays": {"region": "BY", "extra": []},
    "ups": {},
}


def _item(**kwargs):
    base = {"name": "LS-1", "tracking_number": "", "shipment_date": None,
            "posting_date": None}
    base.update(kwargs)
    return base


class TestScanBeatsEstimate(unittest.TestCase):
    def test_scan_marks_delivered_although_estimate_says_in_transit(self):
        """Heute verschickt, morgen kam der unterschriebene Beleg zurück: die
        Schätzung stünde noch auf „unterwegs", der Scan belegt die Zustellung."""
        heute = date.today().isoformat()
        item = _item(posting_date=heute, pod_scan=True, pod_scan_date=heute)
        out = ups_track.resolve_arrivals([item], CONFIG)[0]
        self.assertEqual(out["arrival_status"], "delivered")
        self.assertEqual(out["arrival_method"], "scan")
        self.assertEqual(out["delivered_date"], heute)

    def test_without_scan_the_estimate_stays(self):
        """Gegenprobe: ohne Scan bleibt es bei der Schätzung."""
        heute = date.today().isoformat()
        out = ups_track.resolve_arrivals([_item(posting_date=heute)], CONFIG)[0]
        self.assertEqual(out["arrival_status"], "in_transit")
        self.assertEqual(out["arrival_method"], "fallback")

    def test_scan_without_date_keeps_estimated_arrival(self):
        """Ohne Scandatum bleibt die geschätzte Ankunft als Näherung stehen —
        der Status ist trotzdem belegt."""
        heute = date.today().isoformat()
        out = ups_track.resolve_arrivals(
            [_item(posting_date=heute, pod_scan=True)], CONFIG)[0]
        self.assertEqual(out["arrival_status"], "delivered")
        self.assertEqual(out["arrival_method"], "scan")
        self.assertIsNotNone(out["delivered_date"])

    def test_scan_does_not_override_live_ups_answer(self):
        """UPS ist die genauere Quelle und darf nicht von einem Anhang
        überstimmt werden."""
        calls = []

        def fake_track(tn, token, url):
            calls.append(tn)
            return {"status": "in_transit", "delivered_date": None}

        orig_track, orig_token = ups_track.track_package, ups_track.get_access_token
        ups_track.track_package = fake_track
        ups_track.get_access_token = lambda *a, **k: "token"
        try:
            item = _item(tracking_number="1Z999", posting_date=date.today().isoformat(),
                         pod_scan=True, pod_scan_date=date.today().isoformat())
            out = ups_track.resolve_arrivals([item], CONFIG, "id", "secret")[0]
        finally:
            ups_track.track_package, ups_track.get_access_token = orig_track, orig_token

        self.assertEqual(calls, ["1Z999"])
        self.assertEqual(out["arrival_status"], "in_transit")
        self.assertEqual(out["arrival_method"], "ups")

    def test_old_shipment_without_scan_is_delivered_by_estimate(self):
        """Die bisherige Schätzlogik bleibt unangetastet."""
        alt = (date.today() - timedelta(days=30)).isoformat()
        out = ups_track.resolve_arrivals([_item(posting_date=alt)], CONFIG)[0]
        self.assertEqual(out["arrival_status"], "delivered")
        self.assertEqual(out["arrival_method"], "fallback")

    def test_no_date_at_all_stays_unknown(self):
        out = ups_track.resolve_arrivals([_item(pod_scan=False)], CONFIG)[0]
        self.assertEqual(out["arrival_status"], "unknown")
        self.assertEqual(out["arrival_method"], "none")


if __name__ == "__main__":
    unittest.main()
