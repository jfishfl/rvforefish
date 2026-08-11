import unittest

from foretravel_rvc.audit import AuditLogger
from foretravel_rvc.can import CanFrame
from foretravel_rvc.commands import extended_id
from foretravel_rvc.decode import (
    DGN_AGS_CRITERION_COMMAND,
    DGN_AGS_CRITERION_STATUS,
    DGN_INVERTER_COMMAND,
    DGN_GENERATOR_DEMAND_COMMAND,
    DGN_WATER_PUMP_COMMAND,
    DGN_WATER_PUMP_STATUS,
    decode_frame,
)


class FakeLogger:
    def __init__(self):
        self.info_events = []
        self.warning_events = []

    def info(self, format_string, *values):
        self.info_events.append(format_string % values)

    def warning(self, format_string, *values):
        self.warning_events.append(format_string % values)


def decoded(dgn, payload, source=0xFA):
    return decode_frame(
        CanFrame(1.0, "vecan0", extended_id(dgn, source), payload)
    )


class AuditLoggerTests(unittest.TestCase):
    def test_command_logs_exact_source_dgn_and_payload(self):
        logger = FakeLogger()
        audit = AuditLogger(logger)
        audit.observe(
            decoded(
                DGN_WATER_PUMP_COMMAND,
                bytes.fromhex("FDFFFFFFFFFFFFFF"),
                source=0x9B,
            )
        )
        self.assertIn("src=0x9B", logger.info_events[0])
        self.assertIn("dgn=0x1FFB2", logger.info_events[0])
        self.assertIn("FDFFFFFFFFFFFFFF", logger.info_events[0])

    def test_unchanged_periodic_status_is_deduplicated(self):
        logger = FakeLogger()
        audit = AuditLogger(logger)
        message = decoded(
            DGN_WATER_PUMP_STATUS,
            bytes.fromhex("FDFFFFFFFFFFFFFF"),
        )
        audit.observe(message)
        audit.observe(message)
        self.assertEqual(len(logger.info_events), 1)

    def test_stock_victron_inverter_command_is_observed_but_not_owned(self):
        logger = FakeLogger()
        audit = AuditLogger(logger)
        audit.observe(
            decoded(
                DGN_INVERTER_COMMAND,
                bytes.fromhex("01FDFFFFFFFFFFFF"),
                source=0x9B,
            )
        )
        self.assertIn("kind=inverter_command", logger.info_events[0])
        self.assertIn("src=0x9B", logger.info_events[0])
        self.assertIn("dgn=0x1FFD3", logger.info_events[0])

    def test_generator_demand_request_is_logged(self):
        logger = FakeLogger()
        audit = AuditLogger(logger)
        request = decode_frame(
            CanFrame(
                1.0,
                "vecan0",
                0x18EAFFFA,
                bytes.fromhex("FFFE01FFFFFFFFFF"),
            )
        )
        self.assertEqual(
            request.fields["requested_pgn"], DGN_GENERATOR_DEMAND_COMMAND
        )
        audit.observe(request)
        self.assertIn("RX_REQUEST", logger.info_events[0])

    def test_ags_criterion_status_is_deduplicated_per_instance(self):
        logger = FakeLogger()
        audit = AuditLogger(logger)
        one = decoded(
            DGN_AGS_CRITERION_STATUS,
            bytes.fromhex("01050001F0000AFF"),
        )
        two = decoded(
            DGN_AGS_CRITERION_STATUS,
            bytes.fromhex("02050001F0000AFF"),
        )
        audit.observe(one)
        audit.observe(one)
        audit.observe(two)
        self.assertEqual(len(logger.info_events), 2)
        self.assertIn("instance=1", logger.info_events[0])
        self.assertIn("instance=2", logger.info_events[1])

    def test_ags_criterion_command_is_audited_as_external_command(self):
        logger = FakeLogger()
        audit = AuditLogger(logger)
        audit.observe(
            decoded(
                DGN_AGS_CRITERION_COMMAND,
                bytes.fromhex("01040001F0000AFF"),
                source=0x9B,
            )
        )
        self.assertIn("kind=ags_criterion_command", logger.info_events[0])
        self.assertIn("src=0x9B", logger.info_events[0])

    def test_transmission_is_always_warning_audited(self):
        logger = FakeLogger()
        audit = AuditLogger(logger)
        frame = CanFrame(
            0,
            "vecan0",
            extended_id(DGN_GENERATOR_DEMAND_COMMAND, 0xE2),
            bytes.fromhex("01FCFFFFFFFFFFFF"),
        )
        audit.transmit(frame)
        self.assertIn("AUDIT TX", logger.warning_events[0])


if __name__ == "__main__":
    unittest.main()
