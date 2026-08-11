import unittest

from foretravel_rvc.config import FeatureGate, RuntimeConfig
from foretravel_rvc.main import (
    autofill_startup_action,
    find_nad_collision,
    generator_startup_action,
)


class StartupSafetyDecisionTests(unittest.TestCase):
    def test_configured_rvc_source_collision_is_detected(self):
        items = {
            "/Devices/panel/Nad": {"Value": 0x9B},
            "/Devices/tm102/Nad": {"Value": 0xFA},
        }
        self.assertEqual(
            find_nad_collision(items, 0x9B),
            "/Devices/panel/Nad",
        )
        self.assertIsNone(find_nad_collision(items, 0xE2))

    def test_no_marker_needs_no_action(self):
        self.assertEqual(
            autofill_startup_action(RuntimeConfig(), False), "none"
        )

    def test_stale_marker_without_armed_stop_refuses_startup(self):
        self.assertEqual(
            autofill_startup_action(RuntimeConfig(), True), "refuse"
        )

    def test_stale_marker_with_armed_stop_recovers(self):
        config = RuntimeConfig(
            monitor_only=False,
            source_address=0xE2,
            autofill_stop=FeatureGate(enabled=True, payload_validated=True),
        )
        self.assertEqual(autofill_startup_action(config, True), "recover")

    def test_generator_marker_requires_armed_release(self):
        self.assertEqual(
            generator_startup_action(RuntimeConfig(), True), "refuse"
        )

    def test_generator_marker_with_armed_demand_recovers(self):
        config = RuntimeConfig(
            monitor_only=False,
            source_address=0xE2,
            generator_demand=FeatureGate(
                enabled=True, payload_validated=True
            ),
            generator_orphan_demand_test_passed=True,
            generator_unload_test_passed=True,
            generator_max_run_seconds=3600,
            generator_unloaded_current_threshold_amps=3.0,
            generator_stop_escalation_seconds=900.0,
        )
        self.assertEqual(generator_startup_action(config, True), "recover")


if __name__ == "__main__":
    unittest.main()
