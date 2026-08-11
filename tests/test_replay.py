from collections import Counter
from pathlib import Path
import unittest

from foretravel_rvc import StateReducer, decode_frame, parse_candump_line
from foretravel_rvc.decode import MessageKind


FIXTURE = Path(__file__).parent / "fixtures" / "rvc-baseline.can"


class BaselineReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = [
            parse_candump_line(line)
            for line in FIXTURE.read_text().splitlines()
            if line.strip()
        ]
        cls.messages = [message for frame in cls.frames if (message := decode_frame(frame))]

    def test_fixture_identity(self):
        self.assertEqual(len(self.frames), 1840)

    def test_expected_tm102_message_counts(self):
        counts = Counter(
            message.kind
            for message in self.messages
            if message.frame.source == 0xFA
        )
        self.assertEqual(counts[MessageKind.GENERATOR_DEMAND_STATUS], 6)
        self.assertEqual(counts[MessageKind.WATER_PUMP_STATUS], 6)
        self.assertEqual(counts[MessageKind.AUTOFILL_STATUS], 6)
        self.assertEqual(counts[MessageKind.GENERATOR_STATUS_1], 6)
        self.assertEqual(counts[MessageKind.ATS_STATUS], 0)
        self.assertEqual(counts[MessageKind.GENERATOR_AC_STATUS_1], 0)
        self.assertEqual(counts[MessageKind.THERMOSTAT_AMBIENT_STATUS], 39)

    def test_baseline_reduces_to_known_coach_state(self):
        reducer = StateReducer()
        for message in self.messages:
            reducer.apply(message)

        snapshot = reducer.snapshot
        self.assertIs(snapshot.pump_on, True)
        self.assertIs(snapshot.autofill_operating, False)
        self.assertIs(snapshot.autofill_valve_open, False)
        self.assertIs(snapshot.generator_demand, False)
        self.assertIs(snapshot.generator_internal_demand, False)
        self.assertIs(snapshot.generator_network_demand, False)
        self.assertIs(snapshot.generator_locked, False)
        self.assertEqual(snapshot.generator_status_raw, 0)
        self.assertEqual(snapshot.generator_runtime_minutes, 0x000126E7)
        self.assertAlmostEqual(snapshot.ambient_temperatures_c[250], 34.3125)
        self.assertIsNone(snapshot.ambient_temperatures_c[249])
        self.assertIsNone(snapshot.ambient_temperatures_c[248])

        status = next(
            message
            for message in self.messages
            if message.kind == MessageKind.GENERATOR_STATUS_1
            and message.frame.source == 0xFA
        )
        self.assertEqual(status.fields["status"], "stopped")
        self.assertIsNone(status.fields["engine_load_percent"])
        self.assertIsNone(status.fields["start_battery_voltage"])

    def test_non_tm102_commands_cannot_replace_status(self):
        reducer = StateReducer()
        command = next(
            (
                message
                for message in self.messages
                if message.frame.source != 0xFA
                and message.kind
                in {
                    MessageKind.WATER_PUMP_COMMAND,
                    MessageKind.GENERATOR_DEMAND_COMMAND,
                }
            ),
            None,
        )
        if command is not None:
            reducer.apply(command)
        self.assertIsNone(reducer.snapshot.pump_on)
        self.assertIsNone(reducer.snapshot.generator_demand)


if __name__ == "__main__":
    unittest.main()
