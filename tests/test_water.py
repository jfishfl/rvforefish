import unittest

from foretravel_rvc.can import CanFrame
from foretravel_rvc.commands import extended_id
from foretravel_rvc.config import FeatureGate, RuntimeConfig
from foretravel_rvc.control import CommandRejected, ControlEngine
from foretravel_rvc.decode import (
    DGN_AUTOFILL_STATUS,
    DGN_TANK_STATUS,
    DGN_WATER_PUMP_STATUS,
    MessageKind,
    decode_frame,
)


def message(dgn, payload, timestamp=100.0, source=0xFA):
    return decode_frame(
        CanFrame(timestamp, "vecan0", extended_id(dgn, source), payload)
    )


def proprietary(payload, timestamp=100.0, source=0xFA, destination=0x9B):
    return decode_frame(
        CanFrame(
            timestamp,
            "vecan0",
            (6 << 26) | (0xEF << 16) | (destination << 8) | source,
            bytes(payload),
        )
    )


def pump_status(*, on=False, running=False, hookup=True, timestamp=100.0):
    flags = int(on) | (int(running) << 2) | (int(hookup) << 4)
    return message(
        DGN_WATER_PUMP_STATUS,
        bytes([flags]) + b"\xFF" * 7,
        timestamp,
    )


def autofill_status(*, on=False, valve=False, result=1, timestamp=100.0):
    flags = int(on) | (int(valve) << 2) | (result << 4)
    return message(
        DGN_AUTOFILL_STATUS,
        bytes([flags]) + b"\xFF" * 7,
        timestamp,
    )


def tank_status(level=40, resolution=100, timestamp=100.0):
    return message(
        DGN_TANK_STATUS,
        bytes([0, level, resolution])
        + (200).to_bytes(2, "little")
        + (500).to_bytes(2, "little")
        + b"\xFF",
        timestamp,
    )


def autofill_config(
    *,
    cutoff_raw=180,
    timeout_minutes=15,
    check_pressure=True,
    pump_cancels=True,
    bypass_disables=True,
    timestamp=100.0,
):
    flags = (
        int(pump_cancels)
        | (int(bypass_disables) << 2)
        | (int(check_pressure) << 6)
    )
    return proprietary(
        [0xED, cutoff_raw, 10, timeout_minutes, 100, flags, 2, 160],
        timestamp,
    )


class WaterDecoderTests(unittest.TestCase):
    def test_tank_level_uses_reported_resolution(self):
        decoded = tank_status(level=73, resolution=100)
        self.assertEqual(decoded.fields["relative_level_percent"], 73.0)
        self.assertEqual(decoded.fields["absolute_level_liters"], 200)
        self.assertEqual(decoded.fields["tank_size_liters"], 500)

    def test_invalid_tank_fraction_fails_closed(self):
        for level, resolution in ((10, 0), (10, 0xFF), (101, 100)):
            decoded = tank_status(level=level, resolution=resolution)
            self.assertIsNone(decoded.fields["relative_level_percent"])

    def test_full_water_pump_status_scaling(self):
        flags = 0x15  # enabled, running, water hookup detected
        payload = (
            bytes([flags])
            + (200).to_bytes(2, "little")
            + (300).to_bytes(2, "little")
            + (400).to_bytes(2, "little")
            + b"\x0C"
        )
        decoded = message(DGN_WATER_PUMP_STATUS, payload)
        self.assertIs(decoded.fields["on"], True)
        self.assertIs(decoded.fields["running"], True)
        self.assertIs(decoded.fields["water_hookup_detected"], True)
        self.assertEqual(decoded.fields["pressure_pa"], 20000.0)
        self.assertAlmostEqual(decoded.fields["pressure_psi"], 2.9007548)
        self.assertEqual(decoded.fields["pump_pressure_setting_pa"], 30000.0)
        self.assertEqual(
            decoded.fields["regulator_pressure_setting_pa"], 40000.0
        )
        self.assertEqual(decoded.fields["operating_current_amps"], 12.0)

    def test_water_pump_physical_unit_sentinels_are_unavailable(self):
        for sentinel in (0xFFFE, 0xFFFF):
            payload = b"\x00" + sentinel.to_bytes(2, "little") * 3 + b"\xFF"
            decoded = message(DGN_WATER_PUMP_STATUS, payload)
            self.assertIsNone(decoded.fields["pressure_pa"])
            self.assertIsNone(decoded.fields["pump_pressure_setting_pa"])
            self.assertIsNone(decoded.fields["regulator_pressure_setting_pa"])
            self.assertIsNone(decoded.fields["operating_current_amps"])

        payload = b"\x00" + b"\x00\x00" * 3 + b"\xFE"
        decoded = message(DGN_WATER_PUMP_STATUS, payload)
        self.assertIsNone(decoded.fields["operating_current_amps"])

    def test_autofill_result_and_proprietary_configs(self):
        status = autofill_status(on=False, valve=False, result=2)
        self.assertEqual(status.fields["last_operation"], "timed_out")

        config = autofill_config()
        self.assertEqual(
            config.kind, MessageKind.TM102_AUTOFILL_CONFIG_STATUS
        )
        self.assertEqual(config.fields["cutoff_level_percent"], 90.0)
        self.assertEqual(config.fields["timeout_minutes"], 15.0)
        self.assertIs(config.fields["check_water_pressure"], True)
        self.assertEqual(config.fields["destination"], 0x9B)

        pump = proprietary([0xD4, 0x05, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])
        self.assertEqual(
            pump.kind, MessageKind.TM102_WATER_PUMP_CONFIG_STATUS
        )
        self.assertIs(pump.fields["input_switch_constant_demand"], True)
        self.assertIs(pump.fields["output_relay_latching"], True)
        self.assertIs(pump.fields["bypass_detect_enabled"], True)
        self.assertEqual(pump.fields["implementation"], "internal")


class AutofillInterlockTests(unittest.TestCase):
    def setUp(self):
        self.sent = []

    def config(self, **overrides):
        values = dict(
            monitor_only=False,
            source_address=0xE2,
            autofill_start=FeatureGate(True, True),
            autofill_stop=FeatureGate(True, True),
            autofill_interlocks_verified=True,
            autofill_max_run_seconds=600,
        )
        values.update(overrides)
        return RuntimeConfig(**values)

    def ready_engine(self):
        engine = ControlEngine(self.config(), self.sent.append)
        for decoded in (
            autofill_status(),
            pump_status(),
            tank_status(),
            autofill_config(),
        ):
            engine.observe(decoded, now=100.0)
        return engine

    def test_ready_start_sets_secondary_deadline(self):
        engine = self.ready_engine()
        ready, reason = engine.autofill_start_interlock(now=100.1)
        self.assertTrue(ready, reason)
        engine.request_autofill(True, now=100.1)
        self.assertEqual(self.sent[-1].data.hex().upper(), "FDFFFFFFFFFFFFFF")
        self.assertEqual(engine.autofill_max_run_deadline, 700.1)

    def test_start_requires_current_process_configuration(self):
        engine = ControlEngine(self.config(), self.sent.append)
        for decoded in (autofill_status(), pump_status(), tank_status()):
            engine.observe(decoded, now=100.0)
        with self.assertRaisesRegex(CommandRejected, "configuration"):
            engine.request_autofill(True, now=100.1)

    def test_start_rejects_stale_or_full_fresh_tank(self):
        engine = self.ready_engine()
        engine.observe(autofill_status(timestamp=108.0), now=108.0)
        engine.observe(pump_status(timestamp=108.0), now=108.0)
        with self.assertRaisesRegex(CommandRejected, "tank status"):
            engine.request_autofill(True, now=108.1)

        engine = self.ready_engine()
        engine.observe(tank_status(level=90, resolution=100), now=100.0)
        with self.assertRaisesRegex(CommandRejected, "cutoff"):
            engine.request_autofill(True, now=100.1)

    def test_start_requires_hookup_when_tm102_policy_does(self):
        engine = self.ready_engine()
        engine.observe(pump_status(hookup=False), now=100.0)
        with self.assertRaisesRegex(CommandRejected, "water hookup"):
            engine.request_autofill(True, now=100.1)

    def test_disabled_tm102_timeout_rejects_start(self):
        engine = self.ready_engine()
        engine.observe(autofill_config(timeout_minutes=0), now=100.0)
        with self.assertRaisesRegex(CommandRejected, "timeout"):
            engine.request_autofill(True, now=100.1)

    def test_stop_transmits_even_when_status_is_stale(self):
        config = RuntimeConfig(
            monitor_only=False,
            source_address=0xE2,
            autofill_stop=FeatureGate(True, True),
        )
        engine = ControlEngine(config, self.sent.append)
        engine.observe(autofill_status(on=True), now=100.0)
        engine.request_autofill(False, now=108.1)
        self.assertEqual(self.sent[-1].data.hex().upper(), "FCFFFFFFFFFFFFFF")

    def test_secondary_deadline_and_stale_status_force_stop(self):
        engine = self.ready_engine()
        engine.request_autofill(True, now=100.0)
        engine.tick(now=700.0)
        self.assertEqual(self.sent[-1].data.hex().upper(), "FCFFFFFFFFFFFFFF")
        self.assertFalse(engine.own_autofill_request)

        self.sent.clear()
        engine = self.ready_engine()
        engine.request_autofill(True, now=100.0)
        engine.tick(now=108.0)
        self.assertEqual(self.sent[-1].data.hex().upper(), "FCFFFFFFFFFFFFFF")
        self.assertIn("stale", engine.views["autofill"].fault)

    def test_stop_cancels_an_unacknowledged_start(self):
        engine = self.ready_engine()
        engine.request_autofill(True, now=100.0)
        engine.request_autofill(False, now=100.1)
        self.assertEqual(
            [frame.data.hex().upper() for frame in self.sent],
            ["FDFFFFFFFFFFFFFF", "FCFFFFFFFFFFFFFF"],
        )
        self.assertFalse(engine.pending["autofill"].desired)

    def test_persistent_cleanup_clears_only_after_tm102_reports_off(self):
        events = []
        engine = ControlEngine(
            self.config(),
            self.sent.append,
            autofill_active_hook=events.append,
        )
        for decoded in (
            autofill_status(),
            pump_status(),
            tank_status(),
            autofill_config(),
        ):
            engine.observe(decoded, now=100.0)
        engine.request_autofill(True, now=100.1)
        self.assertEqual(events, [True])
        engine.request_autofill(False, now=100.2)
        self.assertTrue(engine.autofill_cleanup_required)
        self.assertEqual(events, [True])
        engine.observe(autofill_status(timestamp=100.3), now=100.3)
        self.assertFalse(engine.autofill_cleanup_required)
        self.assertEqual(events, [True, False])

    def test_startup_recovery_sends_stop_and_awaits_off_status(self):
        events = []
        engine = ControlEngine(
            self.config(),
            self.sent.append,
            autofill_active_hook=events.append,
        )
        engine.recover_autofill_for_startup(now=100.0)
        self.assertEqual(self.sent[-1].data.hex().upper(), "FCFFFFFFFFFFFFFF")
        self.assertTrue(engine.autofill_cleanup_required)
        self.assertEqual(events, [True])
        engine.observe(autofill_status(timestamp=100.1), now=100.1)
        self.assertFalse(engine.autofill_cleanup_required)
        self.assertEqual(events, [True, False])

    def test_autofill_marker_is_written_before_start_tx(self):
        events = []

        def broken_sender(frame):
            raise OSError("synthetic CAN failure")

        engine = ControlEngine(
            self.config(),
            broken_sender,
            autofill_active_hook=events.append,
        )
        for decoded in (
            autofill_status(),
            pump_status(),
            tank_status(),
            autofill_config(),
        ):
            engine.observe(decoded, now=100.0)
        with self.assertRaisesRegex(OSError, "synthetic CAN failure"):
            engine.request_autofill(True, now=100.1)
        self.assertEqual(events, [True])
        self.assertTrue(engine.autofill_cleanup_required)
        self.assertFalse(engine.own_autofill_request)


if __name__ == "__main__":
    unittest.main()
