import unittest

from foretravel_rvc.can import CanFrame
from foretravel_rvc.commands import extended_id
from foretravel_rvc.config import RuntimeConfig
from foretravel_rvc.control import ControlEngine
from foretravel_rvc.dbus_export import DbusPublisher, STATUS_DISABLED, STATUS_ON
from foretravel_rvc.model import SourceClass, SourceDecision
from foretravel_rvc.victron import VictronAcState
from foretravel_rvc.decode import (
    DGN_AGS_CRITERION_STATUS,
    DGN_AGS_CRITERION_STATUS_2,
    DGN_AGS_DEMAND_CONFIGURATION_STATUS,
    DGN_GENERATOR_DEMAND_STATUS,
    DGN_GENERATOR_START_CONFIG_STATUS,
    DGN_GENERATOR_STATUS_1,
    DGN_AUTOFILL_STATUS,
    DGN_TANK_STATUS,
    DGN_THERMOSTAT_AMBIENT_STATUS,
    DGN_WATER_PUMP_STATUS,
    decode_frame,
)


class FakeService:
    def __init__(self, name, metadata):
        self.name = name
        self.metadata = metadata
        self.paths = {
            "/DeviceInstance": metadata["device_instance"],
            "/ProductName": metadata["product_name"],
            "/Connected": 0,
        }
        self.registered = False
        self.writeable = {}

    def add_path(
        self,
        path,
        value=None,
        writeable=False,
        onchangecallback=None,
        **kwargs
    ):
        self.paths[path] = value
        self.writeable[path] = (writeable, onchangecallback)

    def register(self):
        self.registered = True

    def __setitem__(self, path, value):
        self.paths[path] = value

    def __getitem__(self, path):
        return self.paths[path]


class FakeFactory:
    def __init__(self):
        self.services = []

    def __call__(self, name, **metadata):
        service = FakeService(name, metadata)
        self.services.append(service)
        return service


def message(dgn, payload, timestamp=100.0):
    return decode_frame(
        CanFrame(timestamp, "vecan0", extended_id(dgn, 0xFA), payload)
    )


class DbusProjectionTests(unittest.TestCase):
    def setUp(self):
        self.factory = FakeFactory()
        self.engine = ControlEngine(RuntimeConfig(), lambda frame: None)
        self.publisher = DbusPublisher(
            RuntimeConfig(), self.engine, service_factory=self.factory
        )

    def test_genset_service_is_telemetry_only(self):
        paths = self.publisher.genset.paths
        for forbidden in (
            "/Start",
            "/RemoteStartModeEnabled",
            "/EnableRemoteStartMode",
        ):
            self.assertNotIn(forbidden, paths)
        self.assertTrue(self.publisher.genset.registered)
        self.assertEqual(
            paths["/Foretravel/Ags/ReadOnly"], 1
        )

    def test_monitor_only_switches_are_hidden_and_not_writeable(self):
        path = "/SwitchableOutput/1/State"
        show = "/SwitchableOutput/1/Settings/ShowUIControl"
        self.assertEqual(self.publisher.switch.paths[show], 0)
        self.assertEqual(self.publisher.switch.writeable[path], (False, None))
        self.assertEqual(self.publisher.switch.paths["/Connected"], 1)

    def test_generator_cleanup_state_is_read_only_and_auditable(self):
        self.engine.generator_cleanup_required = True
        self.engine.generator_release_attempts = 2
        self.publisher.refresh(now=100.0)
        paths = self.publisher.genset.paths
        self.assertEqual(
            paths["/Foretravel/Control/CleanupRequired"], 1
        )
        self.assertEqual(paths["/Foretravel/Control/ReleaseAttempts"], 2)
        self.assertEqual(paths["/Foretravel/Control/OwnDemand"], 0)
        self.assertFalse(
            self.publisher.genset.writeable[
                "/Foretravel/Control/CleanupRequired"
            ][0]
        )

    def test_source_classification_is_diagnostic_only(self):
        decision = SourceDecision(
            SourceClass.AC_UNKNOWN,
            "ATS unavailable",
            False,
        )
        state = VictronAcState(
            fresh=True,
            accepting_ac=True,
            l1_voltage=119.2,
            l2_voltage=118.9,
            l1_current=2.0,
            l2_current=1.0,
            input_current_limit=30.0,
            reported_source_raw=1,
        )
        self.publisher.publish_source_diagnostics(
            decision,
            state,
            ats_fresh=False,
            generator_ac_fresh=False,
            now=100.0,
        )
        paths = self.publisher.genset.paths
        self.assertEqual(
            paths["/Foretravel/Source/Classification"], "ac_unknown"
        )
        self.assertEqual(paths["/Foretravel/Source/SafeToLabel"], 0)
        self.assertEqual(
            paths["/Foretravel/Source/VictronReportedName"], "grid"
        )
        self.assertEqual(
            paths["/Foretravel/Source/ActiveInputL1Current"], 2.0
        )
        self.assertEqual(
            paths["/Foretravel/Source/ActiveInputL2Current"], 1.0
        )
        self.assertEqual(
            paths["/Foretravel/Source/ActiveInputTotalCurrent"], 3.0
        )
        self.assertFalse(
            self.publisher.genset.writeable[
                "/Foretravel/Source/Classification"
            ][0]
        )

    def test_generator_unload_diagnostics_fail_closed_and_are_read_only(self):
        self.engine.observe_generator_input(
            generator_source_confirmed=True,
            l1_current=1.0,
            l2_current=0.5,
            now=100.0,
        )
        self.publisher.refresh(now=100.0)
        paths = self.publisher.genset.paths
        self.assertEqual(paths["/Foretravel/Control/InputCurrentFresh"], 1)
        self.assertEqual(paths["/Foretravel/Control/InputL1Current"], 1.0)
        self.assertEqual(paths["/Foretravel/Control/InputL2Current"], 0.5)
        self.assertEqual(paths["/Foretravel/Control/InputTotalCurrent"], 1.5)
        self.assertEqual(
            paths["/Foretravel/Control/UnloadedInterlockReady"], 0
        )
        self.assertIn(
            "not configured",
            paths["/Foretravel/Control/UnloadedInterlockReason"],
        )
        for path in (
            "/Foretravel/Control/InputL1Current",
            "/Foretravel/Control/InputL2Current",
            "/Foretravel/Control/InputTotalCurrent",
            "/Foretravel/Control/UnloadedInterlockReady",
        ):
            self.assertEqual(self.publisher.genset.writeable[path], (False, None))

        self.publisher.refresh(now=108.0)
        self.assertEqual(paths["/Foretravel/Control/InputCurrentFresh"], 0)
        self.assertIsNone(paths["/Foretravel/Control/InputL1Current"])
        self.assertIsNone(paths["/Foretravel/Control/InputL2Current"])
        self.assertIsNone(paths["/Foretravel/Control/InputTotalCurrent"])

    def test_runtime_minutes_are_published_as_seconds(self):
        # stopped, 0x000126E7 = 75495 minutes
        payload = bytes.fromhex("00E7260100FFFFFF")
        decoded = message(DGN_GENERATOR_STATUS_1, payload)
        self.engine.observe(decoded, now=100.0)
        self.publisher.publish(decoded, now=100.0)
        self.assertEqual(
            self.publisher.genset.paths["/Engine/OperatingHours"],
            75495 * 60,
        )
        self.assertEqual(self.publisher.genset.paths["/StatusCode"], 0)

    def test_fresh_pump_status_drives_actual_switch_status(self):
        decoded = message(
            DGN_WATER_PUMP_STATUS,
            bytes.fromhex("FDFFFFFFFFFFFFFF"),
        )
        self.engine.observe(decoded, now=100.0)
        self.publisher.publish(decoded, now=100.0)
        self.assertEqual(
            self.publisher.switch.paths["/SwitchableOutput/1/Status"],
            STATUS_ON,
        )
        self.publisher.refresh(now=108.0)
        self.assertEqual(
            self.publisher.switch.paths["/SwitchableOutput/1/Status"],
            STATUS_DISABLED,
        )

    def test_water_telemetry_and_staleness_are_explicit(self):
        pump_payload = (
            b"\x15"
            + (200).to_bytes(2, "little")
            + (300).to_bytes(2, "little")
            + (400).to_bytes(2, "little")
            + b"\x0C"
        )
        pump = message(DGN_WATER_PUMP_STATUS, pump_payload)
        autofill = message(
            DGN_AUTOFILL_STATUS,
            bytes.fromhex("21FFFFFFFFFFFFFF"),
        )
        tank = message(
            DGN_TANK_STATUS,
            bytes.fromhex("004964C800F401FF"),
        )
        config = decode_frame(
            CanFrame(
                100.0,
                "vecan0",
                0x18EF9BFA,
                bytes([0xED, 180, 10, 15, 100, 0x41, 2, 160]),
            )
        )
        for decoded in (pump, autofill, tank, config):
            self.engine.observe(decoded, now=100.0)
            self.publisher.publish(decoded, now=100.0)

        paths = self.publisher.switch.paths
        self.assertIs(paths["/Foretravel/Pump/Operating"], True)
        self.assertIs(paths["/Foretravel/Pump/Running"], True)
        self.assertAlmostEqual(
            paths["/Foretravel/Pump/SystemPressurePsi"], 2.9007548
        )
        self.assertEqual(
            paths["/Foretravel/Autofill/LastOperation"], "timed_out"
        )
        self.assertEqual(
            paths["/Foretravel/Autofill/Config/CutoffLevelPercent"], 90.0
        )
        self.assertEqual(paths["/Foretravel/Tank/Fresh/LevelPercent"], 73.0)
        self.assertEqual(paths["/Foretravel/Tank/Fresh/Resolution"], 100)

        self.publisher.refresh(now=108.0)
        self.assertEqual(paths["/Foretravel/Pump/Stale"], 1)
        self.assertIsNone(paths["/Foretravel/Pump/Operating"])
        self.assertEqual(paths["/Foretravel/Autofill/Stale"], 1)
        # The prior result is historical and remains visible even while the
        # live operating/valve fields are withdrawn.
        self.assertEqual(
            paths["/Foretravel/Autofill/LastOperation"], "timed_out"
        )
        self.assertEqual(paths["/Foretravel/Tank/Fresh/Stale"], 1)
        self.assertIsNone(paths["/Foretravel/Tank/Fresh/LevelPercent"])

    def test_valid_ambient_temperature_creates_native_service(self):
        decoded = message(
            DGN_THERMOSTAT_AMBIENT_STATUS,
            bytes.fromhex("FA6C26FFFFFFFFFF"),
        )
        self.engine.observe(decoded, now=100.0)
        self.publisher.publish(decoded, now=100.0)
        service = self.publisher.temperature_services[250]
        self.assertEqual(service.metadata["device_instance"], 60)
        self.assertEqual(service.paths["/Temperature"], 34.375)
        self.assertEqual(service.paths["/TemperatureType"], 2)
        self.assertEqual(service.paths["/Connected"], 1)
        self.publisher.refresh(now=108.0)
        self.assertIsNone(service.paths["/Temperature"])
        self.assertEqual(service.paths["/Connected"], 0)

    def test_unconfigured_temperature_instances_do_not_clutter_dbus(self):
        decoded = message(
            DGN_THERMOSTAT_AMBIENT_STATUS,
            bytes.fromhex("F9FEFFFFFFFFFFFF"),
        )
        self.engine.observe(decoded, now=100.0)
        self.publisher.publish(decoded, now=100.0)
        self.assertNotIn(249, self.publisher.temperature_services)

    def test_full_generator_demand_provenance_is_published(self):
        decoded = message(
            DGN_GENERATOR_DEMAND_STATUS,
            bytes.fromhex("55450102030405FF"),
        )
        self.engine.observe(decoded, now=100.0)
        self.publisher.publish(decoded, now=100.0)
        paths = self.publisher.genset.paths
        self.assertIs(paths["/Foretravel/Demand/Overall"], True)
        self.assertIs(paths["/Foretravel/Demand/Internal"], True)
        self.assertIs(paths["/Foretravel/Demand/Network"], True)
        self.assertIs(paths["/Foretravel/Demand/ExternalActivity"], True)
        self.assertIs(paths["/Foretravel/Demand/ManualOverride"], True)
        self.assertIs(paths["/Foretravel/Demand/QuietTime"], True)
        self.assertIs(paths["/Foretravel/Demand/QuietTimeOverride"], False)
        self.assertIs(paths["/Foretravel/Demand/Locked"], True)
        self.assertEqual(
            paths["/Foretravel/Demand/MinimumCycleMinutes"], 5
        )

    def test_ags_criterion_and_counter_are_read_only_diagnostics(self):
        criterion = message(
            DGN_AGS_CRITERION_STATUS,
            bytes.fromhex("01050001F0000AFF"),
        )
        self.engine.observe(criterion, now=100.0)
        self.publisher.publish(criterion, now=100.0)
        base = "/Foretravel/Ags/Criterion/1/"
        paths = self.publisher.genset.paths
        self.assertEqual(paths[base + "Present"], 1)
        self.assertEqual(paths[base + "TypeName"], "house_dc_voltage")
        self.assertEqual(paths[base + "Threshold"], 12.0)
        self.assertEqual(paths[base + "DelaySeconds"], 50.0)
        self.assertEqual(paths["/Foretravel/Ags/CriterionCount"], 1)
        for path in paths:
            if path.startswith(base):
                self.assertEqual(
                    self.publisher.genset.writeable[path], (False, None)
                )

        counter = message(
            DGN_AGS_CRITERION_STATUS_2,
            bytes.fromhex("01000A00FFFFFFFF"),
        )
        self.engine.observe(counter, now=101.0)
        self.publisher.publish(counter, now=101.0)
        self.assertEqual(paths[base + "CounterSeconds"], 10)
        self.assertEqual(paths[base + "CounterLegacyDgn"], 0)

    def test_criterion_type_change_clears_variant_fields(self):
        voltage = message(
            DGN_AGS_CRITERION_STATUS,
            bytes.fromhex("01050001F0000AFF"),
        )
        quiet = message(
            DGN_AGS_CRITERION_STATUS,
            bytes.fromhex("010505FF161E0700"),
        )
        self.engine.observe(voltage, now=100.0)
        self.publisher.publish(voltage, now=100.0)
        self.engine.observe(quiet, now=101.0)
        self.publisher.publish(quiet, now=101.0)
        base = "/Foretravel/Ags/Criterion/1/"
        paths = self.publisher.genset.paths
        self.assertIsNone(paths[base + "Threshold"])
        self.assertEqual(paths[base + "BeginHour"], 22)

    def test_ags_safety_configuration_is_published(self):
        decoded = message(
            DGN_AGS_DEMAND_CONFIGURATION_STATUS,
            bytes.fromhex("401004010A09FFFF"),
        )
        self.engine.observe(decoded, now=100.0)
        self.publisher.publish(decoded, now=100.0)
        base = "/Foretravel/Ags/Safety/"
        paths = self.publisher.genset.paths
        self.assertIs(paths[base + "DisableOnMotion"], True)
        self.assertIs(paths[base + "DisableOnCarbonMonoxide"], True)
        self.assertIs(paths[base + "DisableOnShorePower"], True)
        self.assertEqual(paths[base + "DisableAfterDays"], 10)

    def test_generator_starter_configuration_is_published_read_only(self):
        decoded = message(
            DGN_GENERATOR_START_CONFIG_STATUS,
            bytes.fromhex("030A1E05FFFFFFFF"),
        )
        self.engine.observe(decoded, now=100.0)
        self.publisher.publish(decoded, now=100.0)
        base = "/Foretravel/Ags/Starter/"
        paths = self.publisher.genset.paths
        self.assertEqual(paths[base + "GeneratorType"], 3)
        self.assertEqual(paths[base + "PreCrankSeconds"], 10)
        self.assertEqual(paths[base + "MaximumCrankSeconds"], 30)
        self.assertEqual(paths[base + "StopSeconds"], 5)
        self.assertEqual(paths[base + "LastStatus"], 100.0)
        for path in paths:
            if path.startswith(base):
                self.assertEqual(
                    self.publisher.genset.writeable[path], (False, None)
                )

    def test_tm102_stop_policy_reports_are_merged_read_only(self):
        stop = decode_frame(
            CanFrame(
                100.0,
                "vecan0",
                0x18EF9BFA,
                bytes.fromhex("EF200313FFFF0A00"),
            )
        )
        self.engine.observe(stop, now=100.0)
        self.publisher.publish(stop, now=100.0)
        limit = decode_frame(
            CanFrame(
                101.0,
                "vecan0",
                0x18EF9BFA,
                bytes.fromhex("7F2003FFFFFFFFFF"),
            )
        )
        self.engine.observe(limit, now=101.0)
        self.publisher.publish(limit, now=101.0)
        base = "/Foretravel/Ags/StopPolicy/"
        paths = self.publisher.genset.paths
        self.assertEqual(paths[base + "MaximumRunMinutes"], 800)
        self.assertEqual(paths[base + "MaximumRunLimitMinutes"], 800)
        self.assertEqual(paths[base + "StopCriterion"], 3)
        self.assertIs(paths[base + "DisableOnMovement"], True)
        self.assertEqual(paths[base + "PlusTimeMinutes"], 10)
        self.assertEqual(paths[base + "Destination"], 0x9B)
        self.assertEqual(paths[base + "LastStatus"], 101.0)
        for path in paths:
            if path.startswith(base):
                self.assertEqual(
                    self.publisher.genset.writeable[path], (False, None)
                )


if __name__ == "__main__":
    unittest.main()
