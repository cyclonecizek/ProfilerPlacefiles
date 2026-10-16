import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ksc_915mhz_profiler_placefile as p

class ApiTests(unittest.TestCase):
    def row(self, **changes):
        row=dict(consensus_datetime="2026-10-16T10:00:00", drwp_identifier="RWP0001",
                 altitude_km=1, wind_speed_mps=10, wind_direction_deg=270)
        row.update(changes)
        return row

    def test_units_missing_and_calm(self):
        rows=p.parse_api([self.row(), self.row(wind_speed_mps=9999, wind_direction_deg=9999),
                          self.row(wind_speed_mps=0, wind_direction_deg=0)])
        self.assertIsNone(rows[1].speed_mps)
        self.assertIsNone(rows[1].direction_deg)
        self.assertEqual(rows[2].speed_mps,0)
        profile=p.latest_profiles(rows)["RWP0001"]
        text=p.build_hover("RWP0001",dict(name="Test",elev_m=3),profile,rows[0].dt)
        self.assertIn("3,281 ft",text)
        self.assertIn("19 kt",text)
        self.assertEqual(profile["valid"],2)

    def test_full_profile_exact_request(self):
        now=datetime(2026,10,16,10,5,tzinfo=timezone.utc)
        with patch.object(p,"api_get",side_effect=[[self.row()], [self.row(altitude_km=i/10) for i in range(1,72)]]) as get:
            rows=p.fetch_api_profiles(["RWP0001"],now)
        self.assertEqual(len(rows),71)
        self.assertEqual(get.call_args.args[1],dict(drwp_identifier="RWP0001",date="2026-10-16T10:00:00"))

    def test_stale_fallback_and_source(self):
        now=datetime(2026,10,16,10,5,tzinfo=timezone.utc)
        with patch.object(p,"api_get",return_value=[self.row(consensus_datetime="2026-08-05T11:15:00")]):
            with self.assertRaises(ValueError): p.fetch_api_profiles(["RWP0001"],now)
        with patch.object(p,"fetch_api_profiles",side_effect=ValueError("stale")), patch.object(p,"fetch_export",return_value="csv"), patch.object(p,"parse_csv",return_value=["archive"]):
            rows,source,reason=p.fetch_rows(["RWP0001"],now)
        self.assertEqual(rows,["archive"])
        self.assertIn("fallback",source)
        self.assertEqual(reason,"stale")

if __name__ == "__main__": unittest.main()
