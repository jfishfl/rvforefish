import unittest

from foretravel_rvc.can import CanFrame
from foretravel_rvc.decode import decode_frame


def frame(dgn, payload, source=0xFA):
    return CanFrame(1.0, "vecan0", (dgn << 8) | source, bytes(payload))


class PhysicalUnitScalingTests(unittest.TestCase):
    def test_generator_ac_standard_units(self):
        # Instance 0x11, 120.00 V, 10.00 A, 60.00 Hz, no fault data.
        voltage = 2400
        current = 0x7D00 + 200
        frequency = 60 * 128
        payload = (
            bytes([0x11])
            + voltage.to_bytes(2, "little")
            + current.to_bytes(2, "little")
            + frequency.to_bytes(2, "little")
            + b"\xFF"
        )
        message = decode_frame(frame(0x1FFDF, payload))
        self.assertEqual(message.fields["voltage"], 120.0)
        self.assertEqual(message.fields["current"], 10.0)
        self.assertEqual(message.fields["frequency"], 60.0)
        self.assertEqual(message.fields["generator_instance"], 1)
        self.assertEqual(message.fields["line_instance"], 1)

    def test_generator_status_standard_units(self):
        # Running, 100 minutes, 50% load, 12.50 V starter battery.
        payload = (
            b"\x03"
            + (100).to_bytes(4, "little")
            + b"\x64"
            + (250).to_bytes(2, "little")
        )
        message = decode_frame(frame(0x1FFDC, payload))
        self.assertEqual(message.fields["status"], "running")
        self.assertEqual(message.fields["engine_load_percent"], 50.0)
        self.assertEqual(message.fields["start_battery_voltage"], 12.5)

    def test_unavailable_values_stay_unavailable(self):
        payload = b"\x11" + b"\xFF" * 7
        message = decode_frame(frame(0x1FFDF, payload))
        self.assertIsNone(message.fields["voltage"])
        self.assertIsNone(message.fields["current"])
        self.assertIsNone(message.fields["frequency"])

    def test_ambient_temperature_uses_current_rvc_uint16_scale(self):
        # Live TM-102 payload: instance 250, raw 0x266C.
        message = decode_frame(
            frame(0x1FF9C, bytes.fromhex("FA6C26FFFFFFFFFF"))
        )
        self.assertEqual(message.fields["instance"], 250)
        self.assertEqual(message.fields["temperature_raw"], 0x266C)
        self.assertEqual(message.fields["temperature_c"], 34.375)

    def test_ambient_temperature_invalid_sentinels_are_unavailable(self):
        for raw in (0xFFFE, 0xFFFF):
            payload = bytes([249]) + raw.to_bytes(2, "little") + b"\xFF" * 5
            message = decode_frame(frame(0x1FF9C, payload))
            self.assertIsNone(message.fields["temperature_c"])


if __name__ == "__main__":
    unittest.main()
