import unittest

from foretravel_rvc.can import CanFrame
from foretravel_rvc.socketcan import (
    CAN_EFF_FLAG,
    build_socketcan_filters,
    decode_socketcan_packet,
    encode_socketcan_packet,
)


class SocketCanCodecTests(unittest.TestCase):
    def test_kernel_filters_ignore_source_and_priority(self):
        raw = build_socketcan_filters([0x1FFB3], include_j1939_request=False)
        filter_id = int.from_bytes(raw[:4], "little")
        mask = int.from_bytes(raw[4:8], "little")
        for can_id in (0x01FFB3FA, 0x19FFB39B):
            flagged = can_id | CAN_EFF_FLAG
            self.assertEqual(flagged & mask, filter_id & mask)
        other = 0x01FFB1FA | CAN_EFF_FLAG
        self.assertNotEqual(other & mask, filter_id & mask)

    def test_request_filter_accepts_global_and_destination_specific(self):
        raw = build_socketcan_filters([])
        filter_id = int.from_bytes(raw[:4], "little")
        mask = int.from_bytes(raw[4:8], "little")
        for can_id in (0x18EAFFFA, 0x18EAE29B):
            flagged = can_id | CAN_EFF_FLAG
            self.assertEqual(flagged & mask, filter_id & mask)

    def test_general_pdu1_filter_ignores_destination(self):
        raw = build_socketcan_filters(
            [0x0EF00], include_j1939_request=False
        )
        filter_id = int.from_bytes(raw[:4], "little")
        mask = int.from_bytes(raw[4:8], "little")
        for can_id in (0x18EF9BFA, 0x18EFE2FA, 0x18EFFFFA):
            flagged = can_id | CAN_EFF_FLAG
            self.assertEqual(flagged & mask, filter_id & mask)
        other = 0x18EE9BFA | CAN_EFF_FLAG
        self.assertNotEqual(other & mask, filter_id & mask)

    def test_extended_frame_round_trip(self):
        original = CanFrame(
            1.0,
            "vecan0",
            0x1FFB3FA,
            bytes.fromhex("FDFFFFFFFFFFFFFF"),
        )
        encoded = encode_socketcan_packet(original)
        decoded = decode_socketcan_packet(
            encoded, timestamp=2.0, interface="vecan0"
        )
        self.assertEqual(len(encoded), 16)
        self.assertEqual(decoded.can_id, original.can_id)
        self.assertEqual(decoded.data, original.data)
        self.assertEqual(decoded.timestamp, 2.0)

    def test_standard_identifier_is_rejected(self):
        packet = (0x123).to_bytes(4, "little") + bytes([1, 0, 0, 0, 0xAA]) + b"\x00" * 7
        self.assertEqual(len(packet), 16)
        with self.assertRaisesRegex(ValueError, "29-bit"):
            decode_socketcan_packet(packet, timestamp=0, interface="vecan0")

    def test_invalid_dlc_is_rejected(self):
        packet = (CAN_EFF_FLAG | 0x123).to_bytes(4, "little") + bytes([9]) + b"\x00" * 11
        with self.assertRaisesRegex(ValueError, "data length"):
            decode_socketcan_packet(packet, timestamp=0, interface="vecan0")


if __name__ == "__main__":
    unittest.main()
