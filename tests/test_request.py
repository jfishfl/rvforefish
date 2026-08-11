import unittest

from foretravel_rvc.can import CanFrame, parse_candump_line
from foretravel_rvc.decode import (
    DGN_GENERATOR_DEMAND_COMMAND,
    MessageKind,
    decode_frame,
)


class J1939RequestTests(unittest.TestCase):
    def test_destination_specific_generator_demand_request(self):
        # Priority 6, PGN EA00, destination FA (TM-102), source 9B.
        frame = parse_candump_line(
            "(100.0) vecan0 18EAFA9B#FFFE01FFFFFFFFFF"
        )
        message = decode_frame(frame)

        self.assertEqual(message.kind, MessageKind.REQUEST)
        self.assertEqual(
            message.fields["requested_pgn"], DGN_GENERATOR_DEMAND_COMMAND
        )
        self.assertEqual(message.fields["destination"], 0xFA)
        self.assertFalse(message.fields["global"])

    def test_global_request(self):
        frame = parse_candump_line("(101.0) vecan0 18EAFF80#B3FF01")
        message = decode_frame(frame)

        self.assertEqual(message.kind, MessageKind.REQUEST)
        self.assertTrue(message.fields["global"])
        self.assertEqual(message.fields["requested_pgn"], 0x1FFB3)

    def test_short_request_is_rejected(self):
        frame = CanFrame(1.0, "vecan0", 0x18EAFA9B, b"\xFF\xFE")
        with self.assertRaisesRegex(ValueError, "three-byte"):
            decode_frame(frame)


if __name__ == "__main__":
    unittest.main()
