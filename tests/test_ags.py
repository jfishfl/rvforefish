import unittest

from foretravel_rvc.can import CanFrame
from foretravel_rvc.decode import (
    DGN_AGS_CRITERION_COMMAND,
    DGN_AGS_CRITERION_STATUS,
    DGN_AGS_CRITERION_STATUS_2,
    DGN_AGS_DEMAND_CONFIGURATION_STATUS,
    DGN_GENERATOR_START_CONFIG_STATUS,
    DGN_TM102_LEGACY_AGS_CRITERION_STATUS_2,
    MessageKind,
    decode_frame,
)


def frame(dgn, payload, *, source=0xFA):
    return CanFrame(1.0, "vecan0", (dgn << 8) | source, bytes(payload))


class AgsDecoderTests(unittest.TestCase):
    def test_tm102_uses_documented_five_second_delay(self):
        payload = bytes.fromhex("01050001F0000AFF")
        message = decode_frame(frame(DGN_AGS_CRITERION_STATUS, payload))
        self.assertEqual(message.kind, MessageKind.AGS_CRITERION_STATUS)
        self.assertEqual(message.fields["instance"], 1)
        self.assertIs(message.fields["demand"], True)
        self.assertIs(message.fields["active"], True)
        self.assertEqual(message.fields["criterion_name"], "house_dc_voltage")
        self.assertEqual(message.fields["threshold"], 12.0)
        self.assertEqual(message.fields["delay_seconds"], 50.0)

        modern = decode_frame(
            frame(DGN_AGS_CRITERION_STATUS, payload, source=0x90)
        )
        self.assertEqual(modern.fields["delay_seconds"], 60.0)

    def test_ambient_criterion_decodes_tm102_deadband(self):
        payload = bytes.fromhex("030503FAA0240605")
        message = decode_frame(frame(DGN_AGS_CRITERION_STATUS, payload))
        self.assertEqual(message.fields["monitored_instance"], 250)
        self.assertEqual(message.fields["threshold"], 20.0)
        self.assertEqual(message.fields["delay_seconds"], 30.0)
        self.assertEqual(message.fields["deadband"], 0.5)

    def test_quiet_time_and_soc_criteria(self):
        quiet = decode_frame(
            frame(
                DGN_AGS_CRITERION_STATUS,
                bytes.fromhex("0B0505FF161E0700"),
            )
        )
        self.assertEqual(quiet.fields["criterion_name"], "quiet_time")
        self.assertEqual(quiet.fields["begin_hour"], 22)
        self.assertEqual(quiet.fields["begin_minute"], 30)
        self.assertEqual(quiet.fields["end_hour"], 7)
        self.assertEqual(quiet.fields["end_minute"], 0)

        soc = decode_frame(
            frame(
                DGN_AGS_CRITERION_STATUS,
                bytes.fromhex("0905010178C80CFF"),
            )
        )
        self.assertEqual(soc.fields["start_threshold"], 60.0)
        self.assertEqual(soc.fields["stop_threshold"], 100.0)
        self.assertEqual(soc.fields["delay_seconds"], 60.0)

    def test_tm102_proprietary_criteria(self):
        external_switch = decode_frame(
            frame(
                DGN_AGS_CRITERION_STATUS,
                bytes.fromhex("0705F814FFFFFFFF"),
            )
        )
        self.assertEqual(
            external_switch.fields["criterion_name"], "external_gen_switch"
        )
        self.assertEqual(external_switch.fields["input_delay_seconds"], 5.0)

        external_demand = decode_frame(
            frame(
                DGN_AGS_CRITERION_STATUS,
                bytes.fromhex("0805F8FFFFFFFFFF"),
            )
        )
        self.assertEqual(external_demand.fields["input_delay_seconds"], 5.0)

        exercise = decode_frame(
            frame(
                DGN_AGS_CRITERION_STATUS,
                bytes.fromhex("0605F91110091E06"),
            )
        )
        self.assertEqual(exercise.fields["criterion_name"], "scheduled_exercise")
        self.assertEqual(exercise.fields["day_mask"], 0b1000101)
        self.assertEqual(exercise.fields["begin_hour"], 9)
        self.assertEqual(exercise.fields["begin_minute"], 30)
        self.assertEqual(exercise.fields["run_time_minutes"], 30.0)

        topoff = decode_frame(
            frame(
                DGN_AGS_CRITERION_STATUS,
                bytes.fromhex("0505FA01F0003CFF"),
            )
        )
        self.assertEqual(topoff.fields["threshold"], 12.0)
        self.assertEqual(topoff.fields["run_time_minutes"], 60.0)

    def test_command_is_observed_without_status_demand_field(self):
        message = decode_frame(
            frame(
                DGN_AGS_CRITERION_COMMAND,
                bytes.fromhex("01040001F0000AFF"),
                source=0x9B,
            )
        )
        self.assertEqual(message.kind, MessageKind.AGS_CRITERION_COMMAND)
        self.assertEqual(message.fields["command"], 0)
        self.assertNotIn("demand", message.fields)

    def test_current_and_legacy_status_2_are_distinguished(self):
        payload = bytes.fromhex("01000A00FFFFFFFF")
        current = decode_frame(frame(DGN_AGS_CRITERION_STATUS_2, payload))
        legacy = decode_frame(
            frame(DGN_TM102_LEGACY_AGS_CRITERION_STATUS_2, payload)
        )
        self.assertEqual(current.fields["counter_seconds"], 10)
        self.assertIs(current.fields["legacy_dgn"], False)
        self.assertIs(legacy.fields["legacy_dgn"], True)

    def test_ags_safety_and_starter_config(self):
        safety = decode_frame(
            frame(
                DGN_AGS_DEMAND_CONFIGURATION_STATUS,
                bytes.fromhex("401004010A09FFFF"),
            )
        )
        self.assertIs(safety.fields["disable_on_motion"], True)
        self.assertIs(safety.fields["disable_on_carbon_monoxide"], True)
        self.assertIs(safety.fields["disable_on_manual_operation"], True)
        self.assertIs(safety.fields["disable_on_shore_power"], True)
        self.assertEqual(safety.fields["disable_after_days"], 10)
        self.assertEqual(safety.fields["days_remaining"], 9)

        starter = decode_frame(
            frame(
                DGN_GENERATOR_START_CONFIG_STATUS,
                bytes.fromhex("030A1E05FFFFFFFF"),
            )
        )
        self.assertEqual(starter.fields["generator_type"], 3)
        self.assertEqual(starter.fields["pre_crank_seconds"], 10)
        self.assertEqual(starter.fields["maximum_crank_seconds"], 30)
        self.assertEqual(starter.fields["stop_seconds"], 5)

    def test_tm102_proprietary_stop_reports(self):
        stop = decode_frame(
            CanFrame(
                1.0,
                "vecan0",
                0x18EF9BFA,
                bytes.fromhex("EF200313FFFF0A00"),
            )
        )
        self.assertEqual(stop.kind, MessageKind.TM102_AGS_STOP_STATUS)
        self.assertEqual(stop.fields["maximum_run_minutes"], 800)
        self.assertEqual(stop.fields["stop_criterion"], 3)
        self.assertIs(stop.fields["disable_on_movement"], True)
        self.assertEqual(stop.fields["plus_time_minutes"], 10)
        self.assertEqual(stop.fields["destination"], 0x9B)

        limit = decode_frame(
            CanFrame(
                1.0,
                "vecan0",
                0x18EF9BFA,
                bytes.fromhex("7F2003FFFFFFFFFF"),
            )
        )
        self.assertEqual(
            limit.fields["maximum_run_limit_minutes"], 800
        )


if __name__ == "__main__":
    unittest.main()
