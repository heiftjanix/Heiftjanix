import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ups_track
from lib import io_utils as io

CONFIG = io.load_config()


class TestUpsFallback(unittest.TestCase):
    """Ohne UPS-Zugangsdaten muss der Versanddatum-Fallback greifen."""

    def setUp(self):
        # Sicherstellen, dass keine echten Creds die Fallback-Logik umgehen.
        self._saved = {k: os.environ.pop(k, None)
                       for k in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET")}
        # .env im Repo-Root darf den Test nicht beeinflussen
        ups_track._load_dotenv = lambda: None

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_old_shipment_counts_as_delivered(self):
        old = (date.today() - timedelta(days=10)).isoformat()
        items = [{"name": "LS-1", "tracking_number": "1Z1", "shipment_date": old}]
        out = ups_track.resolve_arrivals(items, CONFIG)
        self.assertEqual(out[0]["arrival_status"], "delivered")
        self.assertEqual(out[0]["arrival_method"], "fallback")

    def test_todays_shipment_is_in_transit(self):
        items = [{"name": "LS-2", "tracking_number": "1Z2",
                  "shipment_date": date.today().isoformat()}]
        out = ups_track.resolve_arrivals(items, CONFIG)
        self.assertEqual(out[0]["arrival_status"], "in_transit")

    def test_no_dates_is_unknown(self):
        items = [{"name": "LS-3", "tracking_number": None}]
        out = ups_track.resolve_arrivals(items, CONFIG)
        self.assertEqual(out[0]["arrival_status"], "unknown")
        self.assertEqual(out[0]["arrival_method"], "none")

    def test_falls_back_to_posting_date(self):
        old = (date.today() - timedelta(days=30)).isoformat()
        items = [{"name": "LS-4", "tracking_number": "1Z4", "posting_date": old}]
        out = ups_track.resolve_arrivals(items, CONFIG)
        self.assertEqual(out[0]["arrival_status"], "delivered")


if __name__ == "__main__":
    unittest.main()
