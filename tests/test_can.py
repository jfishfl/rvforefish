import unittest

from foretravel_rvc.can import CanFrame, parse_candump_line


class CanFrameTests(unittest.TestCase):
    def test_parses_tm102_status_frame(self):
        frame = parse_candump_line(
            "(1784259813.464840) vecan0 01FF80FA#00000000002D05FF"
        )
        self.assertAlmostEqual(frame.timestamp, 1784259813.464840)
        self.assertEqual(frame.interface, "vecan0")
        self.assertEqual(frame.source, 0xFA)
        self.assertEqual(frame.dgn, 0x1FF80)
        self.assertEqual(frame.canonical_pgn, 0x1FF80)
        self.assertIsNone(frame.destination)
        self.assertEqual(frame.data, bytes.fromhex("00000000002D05FF"))

    def test_pdu1_clears_destination_in_canonical_pgn(self):
        frame = CanFrame(
            timestamp=0,
            interface="vecan0",
            can_id=0x00EFFEFA,
            data=b"\x00" * 8,
        )
        self.assertEqual(frame.dgn, 0x0EFFE)
        self.assertEqual(frame.canonical_pgn, 0x0EF00)
        self.assertEqual(frame.destination, 0xFE)

    def test_rejects_bad_payload(self):
        with self.assertRaises(ValueError):
            parse_candump_line("vecan0 01FF80FA#0")


if __name__ == "__main__":
    unittest.main()
