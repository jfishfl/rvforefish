import unittest

from foretravel_rvc.config import FeatureGate, RuntimeConfig


class RuntimeConfigTests(unittest.TestCase):
    def test_default_is_monitor_only_and_cannot_transmit(self):
        config = RuntimeConfig()
        config.validate()
        self.assertFalse(config.transmission_armed)
        self.assertFalse(config.feature_can_transmit("water_pump"))

    def test_tx_requires_an_explicit_source_address(self):
        with self.assertRaisesRegex(ValueError, "source_address"):
            RuntimeConfig(monitor_only=False).validate()

    def test_feature_requires_payload_capture_validation(self):
        with self.assertRaisesRegex(ValueError, "payload_validated"):
            RuntimeConfig(
                water_pump=FeatureGate(enabled=True, payload_validated=False)
            ).validate()

    def test_generator_requires_orphan_demand_failure_test(self):
        with self.assertRaisesRegex(ValueError, "orphan-demand"):
            RuntimeConfig(
                generator_demand=FeatureGate(True, True),
            ).validate()

    def test_generator_requires_explicit_maximum_run_time(self):
        with self.assertRaisesRegex(ValueError, "maximum run"):
            RuntimeConfig(
                generator_demand=FeatureGate(True, True),
                generator_orphan_demand_test_passed=True,
            ).validate()

    def test_generator_requires_verified_unloaded_cooldown(self):
        base = dict(
            generator_demand=FeatureGate(True, True),
            generator_orphan_demand_test_passed=True,
            generator_max_run_seconds=3600,
        )
        with self.assertRaisesRegex(ValueError, "unloaded-cooldown"):
            RuntimeConfig(**base).validate()
        base["generator_unload_test_passed"] = True
        with self.assertRaisesRegex(ValueError, "unloaded-current"):
            RuntimeConfig(**base).validate()
        base["generator_unloaded_current_threshold_amps"] = 3.0
        with self.assertRaisesRegex(ValueError, "stop escalation"):
            RuntimeConfig(**base).validate()

    def test_generator_stop_escalation_covers_confirm_and_cooldown(self):
        with self.assertRaisesRegex(ValueError, "60 seconds of margin"):
            RuntimeConfig(
                generator_stop_escalation_seconds=389,
                generator_cooldown_seconds=300,
                generator_unloaded_confirm_seconds=30,
            ).validate()

    def test_autofill_start_requires_verified_interlocks(self):
        with self.assertRaisesRegex(ValueError, "interlocks"):
            RuntimeConfig(
                autofill_start=FeatureGate(True, True),
            ).validate()

    def test_autofill_start_requires_stop_gate_and_maximum_run(self):
        with self.assertRaisesRegex(ValueError, "stop gate"):
            RuntimeConfig(
                autofill_start=FeatureGate(True, True),
                autofill_interlocks_verified=True,
                autofill_max_run_seconds=600,
            ).validate()
        with self.assertRaisesRegex(ValueError, "maximum run"):
            RuntimeConfig(
                autofill_start=FeatureGate(True, True),
                autofill_stop=FeatureGate(True, True),
                autofill_interlocks_verified=True,
            ).validate()

    def test_autofill_maximum_run_range_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "autofill maximum"):
            RuntimeConfig(autofill_max_run_seconds=59).validate()

    def test_source_label_writer_requires_authoritative_signal(self):
        with self.assertRaisesRegex(ValueError, "authoritative"):
            RuntimeConfig(source_label_writes=True).validate()

    def test_temporary_source_heuristic_is_an_explicit_gate(self):
        with self.assertRaisesRegex(ValueError, "requires source_label_writes"):
            RuntimeConfig(temporary_source_label_heuristic=True).validate()
        RuntimeConfig(
            source_label_writes=True,
            temporary_source_label_heuristic=True,
        ).validate()

    def test_current_limit_switching_requires_the_source_heuristic(self):
        with self.assertRaisesRegex(ValueError, "requires the temporary"):
            RuntimeConfig(automatic_current_limit_switching=True).validate()

    def test_fully_gated_generator_configuration_validates(self):
        config = RuntimeConfig(
            monitor_only=False,
            source_address=0xE2,
            generator_demand=FeatureGate(True, True),
            generator_orphan_demand_test_passed=True,
            generator_unload_test_passed=True,
            generator_max_run_seconds=8 * 60 * 60,
            generator_unloaded_current_threshold_amps=3.0,
            generator_stop_escalation_seconds=15 * 60,
            source_label_writes=True,
            temporary_source_label_heuristic=True,
            automatic_current_limit_switching=True,
        )
        config.validate()
        self.assertTrue(config.can_tx_armed)

    def test_generator_keepalive_interval_is_bounded(self):
        for value in (9.9, 120.1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "keepalive"):
                    RuntimeConfig(generator_keepalive_seconds=value).validate()

        RuntimeConfig(generator_keepalive_seconds=60.0).validate()

    def test_fully_gated_pump_can_transmit(self):
        config = RuntimeConfig(
            monitor_only=False,
            source_address=0xE2,
            water_pump=FeatureGate(True, True),
        )
        config.validate()
        self.assertTrue(config.feature_can_transmit("water_pump"))

    def test_unknown_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            RuntimeConfig.from_dict({"monitor_only": True, "typo": 1})

    def test_safety_gates_require_actual_booleans(self):
        for name in (
            "monitor_only",
            "generator_orphan_demand_test_passed",
            "generator_unload_test_passed",
            "autofill_interlocks_verified",
            "source_label_writes",
            "authoritative_source_signal_verified",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "boolean"):
                    RuntimeConfig.from_dict({name: 1})

    def test_numeric_safety_values_must_be_finite(self):
        for name in (
            "ack_timeout_seconds",
            "generator_keepalive_seconds",
            "generator_unloaded_current_threshold_amps",
            "generator_stop_escalation_seconds",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "finite"):
                    RuntimeConfig.from_dict({name: float("nan")})

    def test_integer_fields_reject_boolean_values(self):
        for name in (
            "tm102_source",
            "source_address",
            "max_retries",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "integer"):
                    RuntimeConfig.from_dict({name: True})

    def test_temperature_device_instance_range_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "temperature"):
            RuntimeConfig(temperature_device_instance_base=32518).validate()


if __name__ == "__main__":
    unittest.main()
