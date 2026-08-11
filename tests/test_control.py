import unittest

from foretravel_rvc.can import CanFrame
from foretravel_rvc.commands import extended_id
from foretravel_rvc.config import FeatureGate, RuntimeConfig
from foretravel_rvc.control import CommandRejected, ControlEngine, ControlPhase
from foretravel_rvc.decode import (
    DGN_AUTOFILL_STATUS,
    DGN_GENERATOR_DEMAND_STATUS,
    DGN_GENERATOR_STATUS_1,
    DGN_WATER_PUMP_STATUS,
    decode_frame,
)


def message(dgn, payload, timestamp=100.0, source=0xFA):
    return decode_frame(
        CanFrame(timestamp, "vecan0", extended_id(dgn, source), payload)
    )


def pump_status(on, timestamp=100.0):
    return message(
        DGN_WATER_PUMP_STATUS,
        bytes([0xFD if on else 0xFC]) + b"\xFF" * 7,
        timestamp,
    )


def generator_demand_status(
    *, lock=False, demand=False, network_demand=False, timestamp=100.0
):
    first = (0x01 if demand else 0x00) | (
        0x10 if network_demand else 0x00
    )
    second = 0x40 if lock else 0x00
    return message(
        DGN_GENERATOR_DEMAND_STATUS,
        bytes([first, second]) + b"\xFF" * 6,
        timestamp,
    )


def generator_status(status, timestamp=100.0):
    return message(
        DGN_GENERATOR_STATUS_1,
        bytes([status, 0, 0, 0, 0, 0, 0xFF, 0xFF]),
        timestamp,
    )


class ControlEngineTests(unittest.TestCase):
    def setUp(self):
        self.sent = []

    def pump_config(self, **overrides):
        values = dict(
            monitor_only=False,
            source_address=0xE2,
            water_pump=FeatureGate(True, True),
        )
        values.update(overrides)
        return RuntimeConfig(**values)

    def generator_config(self, **overrides):
        values = dict(
            monitor_only=False,
            source_address=0xE2,
            generator_demand=FeatureGate(True, True),
            generator_orphan_demand_test_passed=True,
            generator_unload_test_passed=True,
            generator_max_run_seconds=3600,
            generator_unloaded_current_threshold_amps=3.0,
            generator_unloaded_confirm_seconds=30.0,
            generator_stop_escalation_seconds=900.0,
        )
        values.update(overrides)
        return RuntimeConfig(**values)

    def test_monitor_only_rejects_write_even_with_fresh_status(self):
        engine = ControlEngine(RuntimeConfig(), self.sent.append)
        engine.observe(pump_status(False), now=100.0)
        with self.assertRaisesRegex(CommandRejected, "not armed"):
            engine.request_water_pump(True, now=100.1)
        self.assertEqual(self.sent, [])

    def test_pump_command_waits_for_actual_tm102_status(self):
        engine = ControlEngine(self.pump_config(), self.sent.append)
        engine.observe(pump_status(False), now=100.0)
        engine.request_water_pump(True, now=100.1)
        self.assertEqual(self.sent[-1].data.hex().upper(), "FDFFFFFFFFFFFFFF")
        self.assertEqual(
            engine.views["water_pump"].phase, ControlPhase.AWAITING_ACK
        )

        engine.observe(pump_status(True, 100.5), now=100.5)
        self.assertNotIn("water_pump", engine.pending)
        self.assertEqual(engine.views["water_pump"].phase, ControlPhase.IDLE)

    def test_pump_retries_are_bounded(self):
        engine = ControlEngine(
            self.pump_config(ack_timeout_seconds=1, max_retries=2),
            self.sent.append,
        )
        engine.observe(pump_status(False), now=100.0)
        engine.request_water_pump(True, now=100.0)
        engine.tick(now=101.0)
        engine.tick(now=102.0)
        engine.tick(now=103.0)
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(engine.views["water_pump"].phase, ControlPhase.FAULT)

    def test_stale_pump_status_fails_closed(self):
        engine = ControlEngine(self.pump_config(), self.sent.append)
        engine.observe(pump_status(False), now=100.0)
        with self.assertRaisesRegex(CommandRejected, "stale"):
            engine.request_water_pump(True, now=108.1)

    def test_generator_start_request_response_and_cooldown(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(timestamp=100.0), now=100.0)
        engine.observe(generator_status(0, 100.0), now=100.0)
        engine.request_generator(True, now=100.1)
        self.assertEqual(self.sent[-1].data[:2], b"\x01\xFC")

        # TM-102 global request for GENERATOR_DEMAND_COMMAND.
        request = decode_frame(
            CanFrame(
                101.0,
                "vecan0",
                0x18EAFFFA,
                bytes.fromhex("FFFE01FFFFFFFFFF"),
            )
        )
        engine.observe(request, now=101.0)
        self.assertEqual(self.sent[-1].data[:2], b"\x01\xFC")

        engine.observe(generator_demand_status(demand=True, timestamp=101.0), now=101.0)
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.request_generator(False, now=102.0)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.UNLOAD_REQUIRED
        )
        count = len(self.sent)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=102.0,
        )
        engine.tick(now=102.0)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.UNLOAD_REQUIRED
        )
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=132.0,
        )
        engine.observe(
            generator_demand_status(demand=True, timestamp=132.0), now=132.0
        )
        engine.tick(now=132.0)
        self.assertEqual(engine.views["generator"].phase, ControlPhase.COOLDOWN)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=431.9,
        )
        engine.observe(
            generator_demand_status(demand=True, timestamp=431.9), now=431.9
        )
        engine.tick(now=431.9)
        self.assertEqual(len(self.sent), count + 1)
        self.assertEqual(self.sent[-1].data[:2], b"\x01\xFC")
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=432.0,
        )
        engine.observe(
            generator_demand_status(demand=True, timestamp=432.0), now=432.0
        )
        engine.tick(now=432.0)
        self.assertEqual(self.sent[-1].data[:2], b"\x00\xFC")
        self.assertFalse(engine.own_generator_demand)

    def test_generator_lock_rejects_start(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(lock=True), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        with self.assertRaisesRegex(CommandRejected, "lock"):
            engine.request_generator(True, now=100.1)

    def test_stopped_repeat_during_start_does_not_release_demand(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(timestamp=100.0), now=100.0)
        engine.observe(generator_status(0, 100.0), now=100.0)
        engine.request_generator(True, now=100.1)
        engine.observe(
            generator_demand_status(demand=True, timestamp=104.0), now=104.0
        )

        # TM-102 may repeat its old Stopped state while preheat/crank begins.
        engine.observe(generator_status(0, 104.1), now=104.1)

        self.assertTrue(engine.own_generator_demand)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.STARTING
        )
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0].data[:2], b"\x01\xFC")

        engine.observe(generator_status(3, 108.0), now=108.0)
        self.assertEqual(engine.views["generator"].phase, ControlPhase.RUNNING)

    def test_generator_start_timeout_releases_demand(self):
        engine = ControlEngine(
            self.generator_config(generator_start_timeout_seconds=30),
            self.sent.append,
        )
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(generator_demand_status(demand=True, timestamp=129.0), now=129.0)
        engine.tick(now=130.0)
        self.assertEqual(self.sent[-1].data[:2], b"\x00\xFC")
        self.assertEqual(engine.views["generator"].phase, ControlPhase.FAULT)

    def test_generator_marker_clears_only_after_demand_reports_false(self):
        events = []
        engine = ControlEngine(
            self.generator_config(generator_cooldown_seconds=300),
            self.sent.append,
            generator_demand_hook=events.append,
        )
        engine.observe(generator_demand_status(timestamp=100.0), now=100.0)
        engine.observe(generator_status(0, 100.0), now=100.0)
        engine.request_generator(True, now=100.1)
        self.assertEqual(events, [True])
        engine.observe(
            generator_demand_status(demand=True, timestamp=101.0), now=101.0
        )
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.request_generator(False, now=102.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=102.0,
        )
        engine.tick(now=102.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=132.0,
        )
        engine.observe(
            generator_demand_status(demand=True, timestamp=132.0), now=132.0
        )
        engine.tick(now=132.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=432.0,
        )
        engine.observe(
            generator_demand_status(demand=True, timestamp=432.0), now=432.0
        )
        engine.tick(now=432.0)
        self.assertTrue(engine.generator_cleanup_required)
        self.assertEqual(events, [True])

        engine.observe(
            generator_demand_status(
                demand=False, network_demand=True, timestamp=433.0
            ),
            now=433.0,
        )
        self.assertTrue(engine.generator_cleanup_required)
        self.assertEqual(events, [True])

        engine.observe(
            generator_demand_status(
                demand=False, network_demand=False, timestamp=434.0
            ),
            now=434.0,
        )
        self.assertFalse(engine.generator_cleanup_required)
        self.assertEqual(events, [True, False])

    def test_generator_keepalive_reasserts_demand_during_cooldown(self):
        engine = ControlEngine(
            self.generator_config(generator_keepalive_seconds=60.0),
            self.sent.append,
        )
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(
            generator_demand_status(
                demand=True, network_demand=True, timestamp=101.0
            ),
            now=101.0,
        )
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.request_generator(False, now=102.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=102.0,
        )
        engine.tick(now=102.0)
        count = len(self.sent)

        engine.observe(
            generator_demand_status(
                demand=True, network_demand=True, timestamp=160.0
            ),
            now=160.0,
        )
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=160.0,
        )
        engine.tick(now=160.0)

        self.assertEqual(len(self.sent), count + 1)
        self.assertEqual(self.sent[-1].data[:2], b"\x01\xFC")
        self.assertTrue(engine.own_generator_demand)
        self.assertTrue(engine.generator_stop_requested)

    def test_running_recovery_immediately_reasserts_demand(self):
        engine = ControlEngine(
            self.generator_config(generator_keepalive_seconds=60.0),
            self.sent.append,
        )
        engine.recover_generator_for_startup(now=100.0)
        engine.observe(generator_status(3, 100.1), now=100.1)
        engine.observe(
            generator_demand_status(
                demand=True, network_demand=True, timestamp=100.2
            ),
            now=100.2,
        )

        self.assertEqual(self.sent[-1].data[:2], b"\x01\xFC")
        self.assertTrue(engine.own_generator_demand)
        self.assertTrue(engine.generator_stop_requested)
        self.assertEqual(engine.generator_keepalive_at, 160.2)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.UNLOAD_REQUIRED
        )

    def test_generator_startup_recovery_retries_and_awaits_status(self):
        events = []
        engine = ControlEngine(
            self.generator_config(ack_timeout_seconds=1, max_retries=1),
            self.sent.append,
            generator_demand_hook=events.append,
        )
        engine.recover_generator_for_startup(now=100.0)
        self.assertEqual(self.sent, [])
        engine.observe(
            generator_demand_status(
                demand=True, network_demand=True, timestamp=100.1
            ),
            now=100.1,
        )
        engine.observe(generator_status(0, 100.1), now=100.1)
        self.assertEqual(self.sent[-1].data[:2], b"\x00\xFC")
        self.assertTrue(engine.generator_cleanup_required)
        engine.tick(now=101.1)
        self.assertEqual(len(self.sent), 2)
        engine.tick(now=102.1)
        self.assertIn("unconfirmed", engine.views["generator"].fault)
        self.assertTrue(engine.generator_cleanup_required)
        self.assertEqual(events, [True])
        engine.observe(
            generator_demand_status(demand=False, timestamp=102.2),
            now=102.2,
        )
        self.assertFalse(engine.generator_cleanup_required)
        self.assertEqual(events, [True, False])

    def test_generator_recovery_releases_stopped_network_demand(self):
        events = []
        engine = ControlEngine(
            self.generator_config(ack_timeout_seconds=1, max_retries=1),
            self.sent.append,
            generator_demand_hook=events.append,
        )
        engine.recover_generator_for_startup(now=100.0)
        engine.observe(generator_status(0, 100.1), now=100.1)
        engine.observe(
            generator_demand_status(
                demand=False, network_demand=True, timestamp=100.2
            ),
            now=100.2,
        )
        self.assertEqual(self.sent[-1].data[:2], b"\x00\xFC")
        self.assertTrue(engine.generator_cleanup_required)
        self.assertEqual(events, [True])

        engine.observe(
            generator_demand_status(
                demand=False, network_demand=False, timestamp=100.3
            ),
            now=100.3,
        )
        self.assertFalse(engine.generator_cleanup_required)
        self.assertEqual(events, [True, False])

    def test_generator_recovery_clears_when_only_non_network_demand_remains(self):
        events = []
        engine = ControlEngine(
            self.generator_config(),
            self.sent.append,
            generator_demand_hook=events.append,
        )
        engine.recover_generator_for_startup(now=100.0)
        engine.observe(generator_status(0, 100.1), now=100.1)
        engine.observe(
            generator_demand_status(
                demand=True, network_demand=False, timestamp=100.2
            ),
            now=100.2,
        )
        self.assertEqual(self.sent, [])
        self.assertFalse(engine.generator_cleanup_required)
        self.assertEqual(events, [True, False])

    def test_generator_marker_is_written_before_start_tx(self):
        events = []

        def broken_sender(frame):
            raise OSError("synthetic CAN failure")

        engine = ControlEngine(
            self.generator_config(),
            broken_sender,
            generator_demand_hook=events.append,
        )
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        with self.assertRaisesRegex(OSError, "synthetic CAN failure"):
            engine.request_generator(True, now=100.1)
        self.assertEqual(events, [True])
        self.assertTrue(engine.generator_cleanup_required)
        self.assertFalse(engine.own_generator_demand)

    def test_generator_cooldown_resets_if_load_returns(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(generator_demand_status(demand=True, timestamp=101.0), now=101.0)
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.request_generator(False, now=102.0)

        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=102.0,
        )
        engine.tick(now=102.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=132.0,
        )
        engine.observe(generator_demand_status(demand=True, timestamp=132.0), now=132.0)
        engine.tick(now=132.0)
        self.assertEqual(engine.views["generator"].phase, ControlPhase.COOLDOWN)

        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=4.0,
            l2_current=1.0,
            now=133.0,
        )
        engine.observe(generator_demand_status(demand=True, timestamp=133.0), now=133.0)
        engine.tick(now=133.0)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.UNLOAD_REQUIRED
        )
        self.assertIsNone(engine.generator_cooldown_deadline)

    def test_generator_off_request_is_accepted_with_stale_status(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(
            generator_demand_status(demand=True, timestamp=101.0), now=101.0
        )
        engine.observe(generator_status(3, 101.0), now=101.0)
        count = len(self.sent)

        engine.request_generator(False, now=109.0)

        self.assertEqual(len(self.sent), count)
        self.assertTrue(engine.own_generator_demand)
        self.assertTrue(engine.generator_stop_requested)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.UNLOAD_REQUIRED
        )

    def test_stale_demand_status_cannot_bypass_cooldown(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(
            generator_demand_status(demand=True, timestamp=101.0), now=101.0
        )
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.request_generator(False, now=102.0)
        count = len(self.sent)

        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=102.0,
        )
        engine.tick(now=102.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=1.0,
            now=132.0,
        )
        # Demand status is now stale, but the already-started safe stop state
        # must use the independent source/current interlock instead of
        # releasing demand early.
        engine.tick(now=132.0)

        self.assertEqual(len(self.sent), count)
        self.assertTrue(engine.own_generator_demand)
        self.assertEqual(engine.views["generator"].phase, ControlPhase.COOLDOWN)

    def test_stale_demand_during_run_begins_safe_stop(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(
            generator_demand_status(demand=True, timestamp=101.0), now=101.0
        )
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=6.0,
            l2_current=2.0,
            now=109.0,
        )
        count = len(self.sent)

        engine.tick(now=109.0)

        self.assertEqual(len(self.sent), count)
        self.assertTrue(engine.own_generator_demand)
        self.assertTrue(engine.generator_stop_requested)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.UNLOAD_REQUIRED
        )
        self.assertIn("exceeds", engine.views["generator"].fault)

    def test_nonfinite_or_missing_leg_never_proves_unloaded(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=float("nan"),
            l2_current=0.0,
            now=100.0,
        )
        ready, reason = engine.generator_unload_interlock(100.0)
        self.assertFalse(ready)
        self.assertIn("both", reason)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=0.0,
            l2_current=None,
            now=101.0,
        )
        ready, reason = engine.generator_unload_interlock(101.0)
        self.assertFalse(ready)
        self.assertIn("both", reason)

    def test_generator_stop_escalation_retains_demand_under_load(self):
        engine = ControlEngine(
            self.generator_config(generator_stop_escalation_seconds=600.0),
            self.sent.append,
        )
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(generator_demand_status(demand=True, timestamp=101.0), now=101.0)
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.request_generator(False, now=102.0)
        engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=10.0,
            l2_current=10.0,
            now=702.0,
        )
        engine.observe(generator_demand_status(demand=True, timestamp=702.0), now=702.0)
        engine.tick(now=702.0)
        self.assertNotEqual(self.sent[-1].data[:2], b"\x00\xFC")
        self.assertTrue(engine.own_generator_demand)
        self.assertTrue(engine.generator_stop_escalated)
        self.assertEqual(
            engine.views["generator"].phase, ControlPhase.UNLOAD_REQUIRED
        )
        self.assertIn("STOP ESCALATED", engine.views["generator"].fault)

    def test_external_generator_stop_releases_our_demand(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        engine.observe(generator_demand_status(demand=True, timestamp=101.0), now=101.0)
        engine.observe(generator_status(3, 101.0), now=101.0)
        engine.observe(generator_status(0, 102.0), now=102.0)
        self.assertEqual(self.sent[-1].data[:2], b"\x00\xFC")
        self.assertFalse(engine.own_generator_demand)
        self.assertEqual(engine.views["generator"].phase, ControlPhase.FAULT)

    def test_request_from_non_tm102_is_ignored(self):
        engine = ControlEngine(self.generator_config(), self.sent.append)
        engine.observe(generator_demand_status(), now=100.0)
        engine.observe(generator_status(0), now=100.0)
        engine.request_generator(True, now=100.0)
        count = len(self.sent)
        request = decode_frame(
            CanFrame(
                101.0,
                "vecan0",
                0x18EAFF9B,
                bytes.fromhex("FFFE01FFFFFFFFFF"),
            )
        )
        engine.observe(request, now=101.0)
        self.assertEqual(len(self.sent), count)


if __name__ == "__main__":
    unittest.main()
