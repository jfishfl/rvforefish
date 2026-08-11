import unittest

from foretravel_rvc.soak import analyze_soak


def row(epoch, **overrides):
    values = {
        "epoch_utc": str(epoch),
        "service_up": "1",
        "pid": "100",
        "cpu_ticks": str(100 + (epoch - 1000) // 10),
        "rss_kb": "16000",
        "app_kb": "340",
        "log_kb": "8",
        "can_state": "ERROR-ACTIVE",
        "rx_packets": "1000",
        "rx_errors": "4",
        "rx_dropped": "0",
        "tx_packets": "2000",
        "tx_errors": "1",
        "tx_dropped": "0",
        "audit_tx_count": "0",
        "generator_owner_count": "0",
        "battery_service_count": "6",
        "active_bms_present": "1",
        "berr_tx": "0",
        "berr_rx": "0",
        "can_restarts": "0",
        "can_bus_errors": "5",
        "can_error_warn": "0",
        "can_error_passive": "0",
        "can_bus_off": "0",
    }
    values.update({key: str(value) for key, value in overrides.items()})
    return values


class SoakAnalysisTests(unittest.TestCase):
    def test_healthy_soak_passes(self):
        report = analyze_soak(
            [row(1000), row(1300), row(1600)], min_samples=3
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.duration_seconds, 600)
        self.assertEqual(report.errors, ())

    def test_safety_violations_fail(self):
        report = analyze_soak(
            [
                row(1000),
                row(
                    1300,
                    service_up=0,
                    can_state="ERROR-PASSIVE",
                    audit_tx_count=1,
                    generator_owner_count=1,
                    rx_dropped=1,
                ),
            ],
            min_samples=2,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("service down" in error for error in report.errors))
        self.assertTrue(any("bridge TX" in error for error in report.errors))
        self.assertTrue(any("rx_dropped increased" in error for error in report.errors))

    def test_sparse_recovered_errors_warn_but_do_not_fail(self):
        report = analyze_soak(
            [
                row(1000, rx_packets=1000, tx_packets=2000),
                row(
                    1300,
                    rx_packets=101000,
                    tx_packets=202000,
                    rx_errors=5,
                    tx_errors=2,
                ),
            ],
            min_samples=2,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.rx_error_delta, 1)
        self.assertEqual(report.tx_error_delta, 1)
        self.assertEqual(len(report.warnings), 2)

    def test_controller_restart_or_nonzero_berr_fails(self):
        report = analyze_soak(
            [row(1000), row(1300, can_restarts=1, berr_rx=3)],
            min_samples=2,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("can_restarts" in error for error in report.errors))
        self.assertTrue(any("berr_rx" in error for error in report.errors))

    def test_bms_outage_is_separate_warning(self):
        report = analyze_soak(
            [
                row(1000, battery_service_count=5, active_bms_present=0),
                row(1300, battery_service_count=5, active_bms_present=0),
            ],
            min_samples=2,
        )
        self.assertTrue(report.passed)
        self.assertEqual(len(report.warnings), 2)

    def test_missing_samples_and_large_gap_fail(self):
        report = analyze_soak(
            [row(1000), row(1500)],
            min_samples=3,
            expected_interval_seconds=300,
            max_gap_slack_seconds=90,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("only 2 samples" in error for error in report.errors))
        self.assertTrue(any("sample gap" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()
