import unittest

from foretravel_rvc.commands import (
    autofill_command,
    generator_demand_command,
    water_pump_command,
)


class CommandBuilderTests(unittest.TestCase):
    def test_water_pump_commands_leave_unsupported_fields_unavailable(self):
        self.assertEqual(water_pump_command(0xE0, True).dgn, 0x1FFB2)
        self.assertEqual(
            water_pump_command(0xE0, True).data.hex().upper(),
            "FDFFFFFFFFFFFFFF",
        )
        self.assertEqual(
            water_pump_command(0xE0, False).data.hex().upper(),
            "FCFFFFFFFFFFFFFF",
        )

    def test_autofill_does_not_expose_manual_valve(self):
        start = autofill_command(0xE0, True)
        stop = autofill_command(0xE0, False)
        self.assertEqual(start.dgn, 0x1FFB0)
        self.assertEqual(start.data[0] & 0x03, 1)
        self.assertEqual(stop.data[0] & 0x03, 0)
        self.assertEqual((start.data[0] >> 2) & 0x03, 3)
        self.assertEqual((stop.data[0] >> 2) & 0x03, 3)

    def test_generator_demand_is_cooperative(self):
        start = generator_demand_command(0xE0, True)
        stop = generator_demand_command(0xE0, False)
        self.assertEqual(start.dgn, 0x1FEFF)
        self.assertEqual(start.data.hex().upper(), "01FCFFFFFFFFFFFF")
        self.assertEqual(stop.data.hex().upper(), "00FCFFFFFFFFFFFF")
        self.assertEqual(stop.data[0], 0x00)
        self.assertEqual((start.data[0] >> 2) & 0x03, 0)  # quiet override
        self.assertEqual((start.data[0] >> 4) & 0x03, 0)  # no activity reset
        self.assertEqual((start.data[0] >> 6) & 0x03, 0)  # manual override
        self.assertEqual(start.data[1] & 0x03, 0)  # no generator lock
        self.assertEqual((start.data[1] >> 2) & 0x03, 3)  # no activity set

    def test_generator_demand_uses_rvc_priority_six(self):
        frame = generator_demand_command(0xE2, True)
        self.assertEqual((frame.can_id >> 26) & 0x07, 6)
        self.assertEqual(frame.can_id, 0x19FEFFE2)


if __name__ == "__main__":
    unittest.main()
