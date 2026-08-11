import os
import tempfile
import unittest

from foretravel_rvc.can import CanFrame
from foretravel_rvc.decode import DGN_AGS_CRITERION_STATUS, decode_frame
from foretravel_rvc.model import StateReducer
from foretravel_rvc.state import GeneratorDemandMarker


class GeneratorDemandMarkerTests(unittest.TestCase):
    def test_marker_is_atomic_and_removable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "nested", "demand")
            marker = GeneratorDemandMarker(path)
            self.assertFalse(marker.exists())
            marker.set_active(True)
            self.assertTrue(marker.exists())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            marker.set_active(False)
            self.assertFalse(marker.exists())


class AgsStateTests(unittest.TestCase):
    def test_tm102_criteria_are_retained_but_panel_commands_are_not(self):
        reducer = StateReducer()
        payload = bytes.fromhex("01050001F0000AFF")
        status = decode_frame(
            CanFrame(
                1.0,
                "vecan0",
                (DGN_AGS_CRITERION_STATUS << 8) | 0xFA,
                payload,
            )
        )
        reducer.apply(status)
        self.assertEqual(
            reducer.snapshot.ags_criteria[1]["criterion_name"],
            "house_dc_voltage",
        )

        panel = decode_frame(
            CanFrame(
                2.0,
                "vecan0",
                (DGN_AGS_CRITERION_STATUS << 8) | 0x9B,
                bytes.fromhex("0105000190010AFF"),
            )
        )
        reducer.apply(panel)
        self.assertEqual(reducer.snapshot.ags_criteria[1]["threshold"], 12.0)


if __name__ == "__main__":
    unittest.main()
