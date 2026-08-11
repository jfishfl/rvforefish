"""Venus D-Bus projection for TM-102 telemetry and guarded switches."""

from __future__ import annotations

import os
import sys
import logging
from typing import Callable, Dict, Optional

from .config import RuntimeConfig
from .control import CommandRejected, ControlEngine, ControlPhase
from .decode import DecodedMessage, MessageKind


VERSION = "0.5.0-rc4"
LOG = logging.getLogger("foretravel_rvc.dbus")
STATUS_OFF = 0x00
STATUS_ON = 0x09
STATUS_OUTPUT_FAULT = 0x08
STATUS_DISABLED = 0x20
OUTPUT_TYPE_TOGGLE = 1
OUTPUT_FUNCTION_MANUAL = 2


def _genset_status(tm102_status: Optional[int]) -> Optional[int]:
    # Venus genset StatusCode: 0 standby, 1..7 startup, 8 running,
    # 9 stopping, 10 error.
    if tm102_status is None:
        return None
    if tm102_status == 0:
        return 0
    if tm102_status in {1, 2, 4}:
        return 1
    if tm102_status in {3, 6, 7, 8, 9}:
        return 8
    if tm102_status == 5:
        return 10
    return None


def _load_venus_factory():
    search_paths = (
        "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
        "/opt/victronenergy/velib_python",
        "/opt/victronenergy/dbus-switch/ext/velib_python",
    )
    for path in search_paths:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    import dbus  # type: ignore
    from vedbus import VeDbusService  # type: ignore

    def factory(
        service_name: str,
        *,
        device_instance: int,
        product_name: str,
        connection: str,
    ):
        bus = (
            dbus.Bus.get_session(private=True)
            if "DBUS_SESSION_BUS_ADDRESS" in os.environ
            else dbus.Bus.get_system(private=True)
        )
        service = VeDbusService(service_name, bus=bus, register=False)
        service.add_mandatory_paths(
            processname=sys.argv[0],
            processversion=VERSION,
            connection=connection,
            deviceinstance=device_instance,
            productid=None,
            productname=product_name,
            firmwareversion=VERSION,
            hardwareversion=None,
            connected=0,
        )
        return service

    return factory


class DbusPublisher:
    """Project the pure state model onto deliberately separated services."""

    CHANNELS = {
        "water_pump": "1",
        "autofill": "2",
        "generator": "3",
    }

    AGS_CRITERION_INSTANCES = tuple(range(1, 12))
    AGS_CRITERION_FIELDS = {
        "Demand": "demand",
        "Active": "active",
        "Type": "criterion_type",
        "TypeName": "criterion_name",
        "MonitoredInstance": "monitored_instance",
        "Threshold": "threshold",
        "StartThreshold": "start_threshold",
        "StopThreshold": "stop_threshold",
        "DelaySeconds": "delay_seconds",
        "InputDelaySeconds": "input_delay_seconds",
        "Deadband": "deadband",
        "RunTimeMinutes": "run_time_minutes",
        "BeginHour": "begin_hour",
        "BeginMinute": "begin_minute",
        "EndHour": "end_hour",
        "EndMinute": "end_minute",
        "DayMask": "day_mask",
    }
    AGS_SAFETY_FIELDS = {
        "DisableOnParkBrakeRelease": "disable_on_park_brake_release",
        "DisableOnIgnition": "disable_on_ignition",
        "DisableOnDrive": "disable_on_drive",
        "DisableOnMotion": "disable_on_motion",
        "DisableOnOemSwitch": "disable_on_oem_switch",
        "DisableOnServiceBrake": "disable_on_service_brake",
        "DisableOnCarbonMonoxide": "disable_on_carbon_monoxide",
        "DisableOnOpenedCompartment": "disable_on_opened_compartment",
        "DisableOnFireAlarm": "disable_on_fire_alarm",
        "DisableOnManualOperation": "disable_on_manual_operation",
        "DisableOnGensetFault": "disable_on_genset_fault",
        "DisableOnSystemFault": "disable_on_system_fault",
        "DisableOnShorePower": "disable_on_shore_power",
        "DisableOn50AmpShore": "disable_on_50_amp_shore",
        "DisableAfterDays": "disable_after_days",
        "DaysRemaining": "days_remaining",
    }

    def __init__(
        self,
        config: RuntimeConfig,
        engine: ControlEngine,
        *,
        service_factory: Optional[Callable] = None,
    ) -> None:
        self.config = config
        self.engine = engine
        factory = service_factory or _load_venus_factory()
        self._factory = factory

        unique = "uc{:02X}".format(config.tm102_source)
        genset_name = (
            "com.victronenergy.genset.socketcan_{}_di{}_{}".format(
                config.interface,
                config.genset_device_instance,
                unique,
            )
        )
        self.genset = factory(
            genset_name,
            device_instance=config.genset_device_instance,
            product_name="SilverLeaf TM-102 Generator",
            connection="RV-C on {}".format(config.interface),
        )
        self.switch = factory(
            "com.victronenergy.switch.foretravel_rvc",
            device_instance=config.switch_device_instance,
            product_name="Foretravel RV-C Controls",
            connection="RV-C on {}".format(config.interface),
        )
        self._genset_paths = set()
        self._switch_paths = set()
        self._generator_lines_seen = set()
        self._ags_criteria_seen = set()
        self.temperature_services: Dict[int, object] = {}
        self._build_genset_service()
        self._build_switch_service()
        self.genset.register()
        self.switch.register()
        self.switch["/Connected"] = 1

    def _temperature_device_instance(self, rvc_instance: int) -> int:
        # The TM-102 instances observed on this coach count down from 250.
        # Preserve that ordering while keeping stable, non-overlapping Venus
        # device instances (60, 61, 62, ... by default).
        return self.config.temperature_device_instance_base + (250 - rvc_instance)

    def _temperature_service(self, rvc_instance: int):
        service = self.temperature_services.get(rvc_instance)
        if service is not None:
            return service

        service = self._factory(
            "com.victronenergy.temperature.foretravel_rvc_i{}".format(
                rvc_instance
            ),
            device_instance=self._temperature_device_instance(rvc_instance),
            product_name="SilverLeaf TM-102 Temperature",
            connection="RV-C on {}".format(self.config.interface),
        )
        name = "SilverLeaf Ambient {}".format(rvc_instance)
        for path, value in (
            ("/CustomName", name),
            ("/DeviceName", name),
            ("/Serial", "TM102-FA-T{}".format(rvc_instance)),
            ("/Temperature", None),
            # Venus TemperatureType 2 is the generic/basement category.  Do
            # not claim storage vs plumbing until a simultaneous panel capture
            # maps this configurable RV-C instance.
            ("/TemperatureType", 2),
            ("/Status", 0),
            ("/Foretravel/RvcInstance", rvc_instance),
            ("/Foretravel/LastStatus", None),
        ):
            service.add_path(path, value=value, writeable=False)
        service.register()
        service["/Connected"] = 0
        self.temperature_services[rvc_instance] = service
        return service

    def _publish_temperature(self, fields: Dict[str, object], *, now: float) -> None:
        instance = int(fields["instance"])
        temperature = fields["temperature_c"]
        # The TM-102 continuously broadcasts unconfigured instances as
        # 0xFFFE.  Avoid creating dead sensors until an instance has produced
        # at least one valid reading.
        if temperature is None and instance not in self.temperature_services:
            return
        service = self._temperature_service(instance)
        service["/Temperature"] = temperature
        service["/Foretravel/LastStatus"] = now
        service["/Connected"] = int(temperature is not None)

    def _add_genset(self, path: str, value=None) -> None:
        self.genset.add_path(path, value=value, writeable=False)
        self._genset_paths.add(path)

    def _add_switch(
        self,
        path: str,
        value=None,
        *,
        writeable: bool = False,
        callback=None,
    ) -> None:
        self.switch.add_path(
            path,
            value=value,
            writeable=writeable,
            onchangecallback=callback,
        )
        self._switch_paths.add(path)

    def _build_genset_service(self) -> None:
        # Intentionally absent: /Start, /RemoteStartModeEnabled and
        # /EnableRemoteStartMode.  Their presence would invite dbus-generator
        # to become a second control owner.
        for path in (
            "/CustomName",
            "/Serial",
            "/StatusCode",
            "/Engine/OperatingHours",
            "/Engine/Load",
            "/Engine/Speed",
            "/Engine/CoolantTemperature",
            "/StarterVoltage",
            "/Ac/Frequency",
            "/Ac/Power",
            "/Ac/L1/Voltage",
            "/Ac/L1/Current",
            "/Ac/L1/Power",
            "/Ac/L2/Voltage",
            "/Ac/L2/Current",
            "/Ac/L2/Power",
            "/NrOfPhases",
            "/Foretravel/Demand/Overall",
            "/Foretravel/Demand/Internal",
            "/Foretravel/Demand/Network",
            "/Foretravel/Demand/Locked",
            "/Foretravel/Demand/ExternalActivity",
            "/Foretravel/Demand/ManualOverride",
            "/Foretravel/Demand/QuietTime",
            "/Foretravel/Demand/QuietTimeOverride",
            "/Foretravel/Demand/MinimumCycleMinutes",
            "/Foretravel/AtsSource",
            "/Foretravel/LastGeneratorStatus",
            "/Foretravel/LastGeneratorAc",
            "/Foretravel/LastDemandStatus",
            "/Foretravel/Source/Classification",
            "/Foretravel/Source/Reason",
            "/Foretravel/Source/SafeToLabel",
            "/Foretravel/Source/VeBusObservationFresh",
            "/Foretravel/Source/VeBusAcceptingAc",
            "/Foretravel/Source/ActiveInputVoltage",
            "/Foretravel/Source/ActiveInputL1Current",
            "/Foretravel/Source/ActiveInputL2Current",
            "/Foretravel/Source/ActiveInputTotalCurrent",
            "/Foretravel/Source/VictronReportedRaw",
            "/Foretravel/Source/VictronReportedName",
            "/Foretravel/Source/AtsFresh",
            "/Foretravel/Source/GeneratorAcFresh",
            "/Foretravel/Source/LastEvaluation",
            "/Foretravel/Control/Requested",
            "/Foretravel/Control/Phase",
            "/Foretravel/Control/Fault",
            "/Foretravel/Control/OwnDemand",
            "/Foretravel/Control/CleanupRequired",
            "/Foretravel/Control/RecoveryPending",
            "/Foretravel/Control/ShutdownRequested",
            "/Foretravel/Control/StopEscalated",
            "/Foretravel/Control/ReleaseAttempts",
            "/Foretravel/Control/KeepaliveRemainingSeconds",
            "/Foretravel/Control/GeneratorSourceConfirmed",
            "/Foretravel/Control/InputCurrentFresh",
            "/Foretravel/Control/InputL1Current",
            "/Foretravel/Control/InputL2Current",
            "/Foretravel/Control/InputTotalCurrent",
            "/Foretravel/Control/UnloadedThresholdAmps",
            "/Foretravel/Control/UnloadedInterlockReady",
            "/Foretravel/Control/UnloadedInterlockReason",
            "/Foretravel/Control/UnloadedConfirmRemainingSeconds",
            "/Foretravel/Control/StartRemainingSeconds",
            "/Foretravel/Control/CooldownRemainingSeconds",
            "/Foretravel/Control/MaxRunRemainingSeconds",
            "/Foretravel/Control/StopEscalationRemainingSeconds",
            "/Foretravel/Ags/ReadOnly",
            "/Foretravel/Ags/CriterionCount",
            "/Foretravel/Ags/LastCriterionStatus",
            "/Foretravel/Ags/LastCriterionCounter",
        ):
            self._add_genset(path)
        for instance in self.AGS_CRITERION_INSTANCES:
            base = "/Foretravel/Ags/Criterion/{}/".format(instance)
            for leaf in (
                "Present",
                "CounterSeconds",
                "CounterLegacyDgn",
                "Raw",
                "LastStatus",
                "LastCounter",
                *self.AGS_CRITERION_FIELDS.keys(),
            ):
                self._add_genset(base + leaf)
        for leaf in self.AGS_SAFETY_FIELDS:
            self._add_genset("/Foretravel/Ags/Safety/" + leaf)
        for leaf in ("LegacyDgn", "Raw", "LastStatus"):
            self._add_genset("/Foretravel/Ags/Safety/" + leaf)
        for leaf in (
            "GeneratorType",
            "PreCrankSeconds",
            "MaximumCrankSeconds",
            "StopSeconds",
            "Raw",
            "LastStatus",
        ):
            self._add_genset("/Foretravel/Ags/Starter/" + leaf)
        for leaf in (
            "MaximumRunMinutes",
            "MaximumRunLimitMinutes",
            "StopCriterion",
            "DisableOnMovement",
            "MainChargerInstance",
            "SecondChargerInstance",
            "PlusTimeMinutes",
            "Destination",
            "Raw",
            "LastStatus",
        ):
            self._add_genset("/Foretravel/Ags/StopPolicy/" + leaf)
        self.genset["/CustomName"] = "Coach Generator"
        self.genset["/Serial"] = "TM102-FA"
        self.genset["/Foretravel/Ags/ReadOnly"] = 1
        self.genset["/Foretravel/Ags/CriterionCount"] = 0
        # The TM-102 application document reports generator instance 1, line 1
        # (0x11).  Do not advertise a measured second phase unless a future
        # capture actually supplies a line-2 instance.
        self.genset["/NrOfPhases"] = 1

    def publish_source_diagnostics(
        self,
        decision,
        ac_state,
        *,
        ats_fresh: bool,
        generator_ac_fresh: bool,
        now: float,
    ) -> None:
        """Publish a read-only classification; never rewrite Victron settings."""

        self.genset["/Foretravel/Source/Classification"] = (
            decision.source.value
        )
        self.genset["/Foretravel/Source/Reason"] = decision.reason
        self.genset["/Foretravel/Source/SafeToLabel"] = int(
            decision.safe_to_write_victron_label
        )
        self.genset["/Foretravel/Source/VeBusObservationFresh"] = int(
            ac_state.fresh
        )
        self.genset["/Foretravel/Source/VeBusAcceptingAc"] = int(
            ac_state.accepting_ac
        )
        self.genset["/Foretravel/Source/ActiveInputVoltage"] = (
            ac_state.active_input_voltage
        )
        self.genset["/Foretravel/Source/ActiveInputL1Current"] = (
            ac_state.active_input_l1_current
        )
        self.genset["/Foretravel/Source/ActiveInputL2Current"] = (
            ac_state.active_input_l2_current
        )
        self.genset["/Foretravel/Source/ActiveInputTotalCurrent"] = (
            ac_state.active_input_total_current
        )
        self.genset["/Foretravel/Source/VictronReportedRaw"] = (
            ac_state.reported_source_raw
        )
        self.genset["/Foretravel/Source/VictronReportedName"] = (
            ac_state.reported_source
        )
        self.genset["/Foretravel/Source/AtsFresh"] = int(ats_fresh)
        self.genset["/Foretravel/Source/GeneratorAcFresh"] = int(
            generator_ac_fresh
        )
        self.genset["/Foretravel/Source/LastEvaluation"] = now

    def _show_control(self, name: str) -> int:
        if self.config.monitor_only:
            return 0
        if name == "water_pump":
            return int(self.config.feature_can_transmit("water_pump"))
        if name == "autofill":
            return int(
                self.config.feature_can_transmit("autofill_start")
                or self.config.feature_can_transmit("autofill_stop")
            )
        return int(self.config.feature_can_transmit("generator_demand"))

    def _build_switch_service(self) -> None:
        self._add_switch("/CustomName", "Foretravel Coach Controls")
        self._add_switch("/Serial", "FORETRAVEL-RVC")
        self._add_switch("/State", 0x100)

        names = {
            "water_pump": "Water Pump",
            "autofill": "Fresh Water Autofill",
            "generator": "Generator Request",
        }
        for name, channel in self.CHANNELS.items():
            base = "/SwitchableOutput/{}/".format(channel)
            show = self._show_control(name)
            callback = self._switch_callback(name) if show else None
            self._add_switch(
                base + "State",
                0,
                writeable=bool(show),
                callback=callback,
            )
            self._add_switch(base + "Status", STATUS_DISABLED)
            self._add_switch(base + "Name", names[name])
            self._add_switch(base + "Settings/Group", "Coach")
            self._add_switch(base + "Settings/CustomName", names[name])
            self._add_switch(base + "Settings/ShowUIControl", show)
            self._add_switch(base + "Settings/Type", OUTPUT_TYPE_TOGGLE)
            self._add_switch(base + "Settings/ValidTypes", 3)
            self._add_switch(base + "Settings/Function", OUTPUT_FUNCTION_MANUAL)
            self._add_switch(base + "Settings/ValidFunctions", 4)

        for leaf in (
            "Operating",
            "Running",
            "WaterHookupDetected",
            "SystemPressurePa",
            "SystemPressurePsi",
            "PumpPressureSettingPa",
            "PumpPressureSettingPsi",
            "RegulatorPressureSettingPa",
            "RegulatorPressureSettingPsi",
            "OperatingCurrentAmps",
            "Stale",
            "Fault",
            "LastStatus",
            "Config/InputSwitchConstantDemand",
            "Config/OutputRelayLatching",
            "Config/BypassDetectEnabled",
            "Config/ImplementationRaw",
            "Config/Implementation",
            "Config/ExternalRvcInstance",
            "Config/Destination",
            "Config/Raw",
            "Config/LastStatus",
        ):
            self._add_switch("/Foretravel/Pump/" + leaf)

        for leaf in (
            "Operating",
            "ValveOpen",
            "LastOperationRaw",
            "LastOperation",
            "Stale",
            "Fault",
            "LastStatus",
            "InterlockReady",
            "InterlockReason",
            "RemainingMaxRunSeconds",
            "Config/CutoffLevelPercent",
            "Config/RunAfterSeconds",
            "Config/TimeoutMinutes",
            "Config/AutoStartLevelPercent",
            "Config/PumpOnCancelsFill",
            "Config/PumpBypassDisablesFill",
            "Config/IgnorePump",
            "Config/CheckWaterPressure",
            "Config/ExtendedRunAfterMinutes",
            "Config/BlackTankWarningPercent",
            "Config/Destination",
            "Config/Raw",
            "Config/LastStatus",
        ):
            self._add_switch("/Foretravel/Autofill/" + leaf)

        for name in ("Fresh", "Black", "Gray", "Lpg"):
            for leaf in (
                "LevelPercent",
                "Resolution",
                "AbsoluteLevelLiters",
                "TankSizeLiters",
                "Stale",
                "LastStatus",
            ):
                self._add_switch(
                    "/Foretravel/Tank/{}/{}".format(name, leaf)
                )

    def _switch_callback(self, name: str):
        def callback(path, value):
            if value not in (0, 1, False, True):
                return False
            try:
                if name == "water_pump":
                    self.engine.request_water_pump(bool(value))
                elif name == "autofill":
                    self.engine.request_autofill(bool(value))
                else:
                    self.engine.request_generator(bool(value))
            except CommandRejected as error:
                LOG.warning("AUDIT REJECT channel=%s reason=%s", name, error)
                return False
            return True

        return callback

    def _publish_ags_criterion(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        instance = int(fields["instance"])
        if instance not in self.AGS_CRITERION_INSTANCES:
            LOG.warning(
                "AGS criterion instance %s is outside documented TM-102 set",
                instance,
            )
            return
        base = "/Foretravel/Ags/Criterion/{}/".format(instance)
        self._ags_criteria_seen.add(instance)
        self.genset[base + "Present"] = 1
        # A criterion can change type.  Clear every variant path before
        # projecting the new payload so stale parameters are never mixed.
        for leaf in self.AGS_CRITERION_FIELDS:
            self.genset[base + leaf] = None
        for leaf, field in self.AGS_CRITERION_FIELDS.items():
            if field in fields:
                self.genset[base + leaf] = fields[field]
        self.genset[base + "Raw"] = fields["raw"]
        self.genset[base + "LastStatus"] = now
        self.genset["/Foretravel/Ags/CriterionCount"] = len(
            self._ags_criteria_seen
        )
        self.genset["/Foretravel/Ags/LastCriterionStatus"] = now

    def _publish_ags_criterion_counter(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        instance = int(fields["instance"])
        if instance not in self.AGS_CRITERION_INSTANCES:
            return
        base = "/Foretravel/Ags/Criterion/{}/".format(instance)
        self.genset[base + "CounterSeconds"] = fields["counter_seconds"]
        self.genset[base + "CounterLegacyDgn"] = int(
            bool(fields["legacy_dgn"])
        )
        self.genset[base + "LastCounter"] = now
        self.genset["/Foretravel/Ags/LastCriterionCounter"] = now

    def _publish_ags_safety(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        base = "/Foretravel/Ags/Safety/"
        for leaf, field in self.AGS_SAFETY_FIELDS.items():
            self.genset[base + leaf] = fields[field]
        self.genset[base + "LegacyDgn"] = int(bool(fields["legacy_dgn"]))
        self.genset[base + "Raw"] = fields["raw"]
        self.genset[base + "LastStatus"] = now

    def _publish_starter_config(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        base = "/Foretravel/Ags/Starter/"
        mapping = {
            "GeneratorType": "generator_type",
            "PreCrankSeconds": "pre_crank_seconds",
            "MaximumCrankSeconds": "maximum_crank_seconds",
            "StopSeconds": "stop_seconds",
        }
        for leaf, field in mapping.items():
            self.genset[base + leaf] = fields[field]
        self.genset[base + "Raw"] = fields["raw"]
        self.genset[base + "LastStatus"] = now

    def _publish_stop_policy(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        base = "/Foretravel/Ags/StopPolicy/"
        mapping = {
            "MaximumRunMinutes": "maximum_run_minutes",
            "MaximumRunLimitMinutes": "maximum_run_limit_minutes",
            "StopCriterion": "stop_criterion",
            "DisableOnMovement": "disable_on_movement",
            "MainChargerInstance": "main_charger_instance",
            "SecondChargerInstance": "second_charger_instance",
            "PlusTimeMinutes": "plus_time_minutes",
            "Destination": "destination",
        }
        for leaf, field in mapping.items():
            if field in fields:
                self.genset[base + leaf] = fields[field]
        self.genset[base + "Raw"] = fields["raw"]
        self.genset[base + "LastStatus"] = now

    def _publish_pump_status(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        base = "/Foretravel/Pump/"
        mapping = {
            "Operating": "on",
            "Running": "running",
            "WaterHookupDetected": "water_hookup_detected",
            "SystemPressurePa": "pressure_pa",
            "SystemPressurePsi": "pressure_psi",
            "PumpPressureSettingPa": "pump_pressure_setting_pa",
            "PumpPressureSettingPsi": "pump_pressure_setting_psi",
            "RegulatorPressureSettingPa": "regulator_pressure_setting_pa",
            "RegulatorPressureSettingPsi": "regulator_pressure_setting_psi",
            "OperatingCurrentAmps": "operating_current_amps",
        }
        for leaf, field in mapping.items():
            self.switch[base + leaf] = fields[field]
        self.switch[base + "Stale"] = 0
        self.switch[base + "LastStatus"] = now

    def _publish_pump_config(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        base = "/Foretravel/Pump/Config/"
        mapping = {
            "InputSwitchConstantDemand": "input_switch_constant_demand",
            "OutputRelayLatching": "output_relay_latching",
            "BypassDetectEnabled": "bypass_detect_enabled",
            "ImplementationRaw": "implementation_raw",
            "Implementation": "implementation",
            "ExternalRvcInstance": "external_rvc_instance",
            "Destination": "destination",
            "Raw": "raw",
        }
        for leaf, field in mapping.items():
            self.switch[base + leaf] = fields[field]
        self.switch[base + "LastStatus"] = now

    def _publish_autofill_status(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        base = "/Foretravel/Autofill/"
        mapping = {
            "Operating": "operating",
            "ValveOpen": "valve_open",
            "LastOperationRaw": "last_operation_raw",
            "LastOperation": "last_operation",
        }
        for leaf, field in mapping.items():
            self.switch[base + leaf] = fields[field]
        self.switch[base + "Stale"] = 0
        self.switch[base + "LastStatus"] = now

    def _publish_autofill_config(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        base = "/Foretravel/Autofill/Config/"
        mapping = {
            "CutoffLevelPercent": "cutoff_level_percent",
            "RunAfterSeconds": "run_after_seconds",
            "TimeoutMinutes": "timeout_minutes",
            "AutoStartLevelPercent": "auto_start_level_percent",
            "PumpOnCancelsFill": "pump_on_cancels_fill",
            "PumpBypassDisablesFill": "pump_bypass_disables_fill",
            "IgnorePump": "ignore_pump",
            "CheckWaterPressure": "check_water_pressure",
            "ExtendedRunAfterMinutes": "extended_run_after_minutes",
            "BlackTankWarningPercent": "black_tank_warning_percent",
            "Destination": "destination",
            "Raw": "raw",
        }
        for leaf, field in mapping.items():
            self.switch[base + leaf] = fields[field]
        self.switch[base + "LastStatus"] = now

    def _publish_tank_status(
        self, fields: Dict[str, object], *, now: float
    ) -> None:
        tank_name = {0: "Fresh", 1: "Black", 2: "Gray", 3: "Lpg"}.get(
            fields["instance"]
        )
        if tank_name is None:
            return
        base = "/Foretravel/Tank/{}/".format(tank_name)
        mapping = {
            "LevelPercent": "relative_level_percent",
            "Resolution": "resolution",
            "AbsoluteLevelLiters": "absolute_level_liters",
            "TankSizeLiters": "tank_size_liters",
        }
        for leaf, field in mapping.items():
            self.switch[base + leaf] = fields[field]
        self.switch[base + "Stale"] = 0
        self.switch[base + "LastStatus"] = now

    def publish(self, message: DecodedMessage, *, now: float) -> None:
        kind = message.kind
        fields = message.fields
        if message.frame.source != self.config.tm102_source:
            self.refresh(now=now)
            return

        self.genset["/Connected"] = 1
        if kind == MessageKind.GENERATOR_DEMAND_STATUS:
            self.genset["/Foretravel/Demand/Overall"] = fields["demand"]
            self.genset["/Foretravel/Demand/Internal"] = fields["internal_demand"]
            self.genset["/Foretravel/Demand/Network"] = fields["network_demand"]
            self.genset["/Foretravel/Demand/Locked"] = fields["generator_lock"]
            self.genset["/Foretravel/Demand/ExternalActivity"] = fields[
                "external_activity"
            ]
            self.genset["/Foretravel/Demand/ManualOverride"] = fields[
                "manual_override"
            ]
            self.genset["/Foretravel/Demand/QuietTime"] = fields[
                "quiet_time"
            ]
            self.genset["/Foretravel/Demand/QuietTimeOverride"] = fields[
                "quiet_time_override"
            ]
            minimum_cycle = fields["minimum_cycle_time_raw"]
            self.genset["/Foretravel/Demand/MinimumCycleMinutes"] = (
                None if minimum_cycle > 250 else minimum_cycle
            )
            self.genset["/Foretravel/LastDemandStatus"] = now
        elif kind == MessageKind.AGS_CRITERION_STATUS:
            self._publish_ags_criterion(fields, now=now)
        elif kind == MessageKind.AGS_CRITERION_STATUS_2:
            self._publish_ags_criterion_counter(fields, now=now)
        elif kind == MessageKind.AGS_DEMAND_CONFIGURATION_STATUS:
            self._publish_ags_safety(fields, now=now)
        elif kind == MessageKind.GENERATOR_START_CONFIG_STATUS:
            self._publish_starter_config(fields, now=now)
        elif kind in {
            MessageKind.TM102_AGS_STOP_STATUS,
            MessageKind.TM102_AGS_STOP_LIMIT_STATUS,
        }:
            self._publish_stop_policy(fields, now=now)
        elif kind == MessageKind.GENERATOR_STATUS_1:
            self.genset["/StatusCode"] = _genset_status(fields["status_raw"])
            self.genset["/Engine/OperatingHours"] = (
                fields["runtime_minutes"] * 60
            )
            self.genset["/Engine/Load"] = fields["engine_load_percent"]
            self.genset["/StarterVoltage"] = fields["start_battery_voltage"]
            self.genset["/Foretravel/LastGeneratorStatus"] = now
        elif kind == MessageKind.GENERATOR_STATUS_2:
            self.genset["/Engine/Speed"] = fields["engine_rpm"]
            self.genset["/Engine/CoolantTemperature"] = fields[
                "coolant_temperature"
            ]
        elif kind == MessageKind.GENERATOR_AC_STATUS_1:
            voltage = fields["voltage"]
            current = fields["current"]
            power = (
                None
                if voltage is None or current is None
                else voltage * current
            )
            line_instance = fields["line_instance"]
            line = 2 if line_instance == 2 else 1
            self._generator_lines_seen.add(line)
            base = "/Ac/L{}/".format(line)
            self.genset["/Ac/Frequency"] = fields["frequency"]
            self.genset[base + "Voltage"] = voltage
            self.genset[base + "Current"] = current
            self.genset[base + "Power"] = power
            self.genset["/NrOfPhases"] = max(self._generator_lines_seen)
            line_powers = [
                self.genset["/Ac/L{}/Power".format(number)]
                for number in self._generator_lines_seen
            ]
            self.genset["/Ac/Power"] = (
                None
                if any(value is None for value in line_powers)
                else sum(line_powers)
            )
            self.genset["/Foretravel/LastGeneratorAc"] = now
        elif kind == MessageKind.ATS_STATUS:
            self.genset["/Foretravel/AtsSource"] = fields["source"]
        elif kind == MessageKind.WATER_PUMP_STATUS:
            self._publish_pump_status(fields, now=now)
        elif kind == MessageKind.TM102_WATER_PUMP_CONFIG_STATUS:
            self._publish_pump_config(fields, now=now)
        elif kind == MessageKind.AUTOFILL_STATUS:
            self._publish_autofill_status(fields, now=now)
        elif kind == MessageKind.TM102_AUTOFILL_CONFIG_STATUS:
            self._publish_autofill_config(fields, now=now)
        elif kind == MessageKind.TANK_STATUS:
            self._publish_tank_status(fields, now=now)
        elif kind == MessageKind.THERMOSTAT_AMBIENT_STATUS:
            self._publish_temperature(fields, now=now)

        self.refresh(now=now)

    def _switch_status(self, name: str, actual: Optional[bool], fresh: bool) -> int:
        view = self.engine.views[name]
        if view.phase == ControlPhase.FAULT:
            return STATUS_OUTPUT_FAULT
        if not fresh or actual is None:
            return STATUS_DISABLED
        return STATUS_ON if actual else STATUS_OFF

    def refresh(self, *, now: float) -> None:
        snapshot = self.engine.reducer.snapshot
        fresh = self.engine._fresh
        generator_view = self.engine.views["generator"]
        self.genset["/Foretravel/Control/Requested"] = (
            generator_view.requested
        )
        self.genset["/Foretravel/Control/Phase"] = generator_view.phase.value
        self.genset["/Foretravel/Control/Fault"] = generator_view.fault
        self.genset["/Foretravel/Control/OwnDemand"] = int(
            self.engine.own_generator_demand
        )
        self.genset["/Foretravel/Control/CleanupRequired"] = int(
            self.engine.generator_cleanup_required
        )
        self.genset["/Foretravel/Control/RecoveryPending"] = int(
            self.engine.generator_recovery_pending
        )
        self.genset["/Foretravel/Control/ShutdownRequested"] = int(
            self.engine.generator_shutdown_requested
        )
        self.genset["/Foretravel/Control/StopEscalated"] = int(
            self.engine.generator_stop_escalated
        )
        self.genset["/Foretravel/Control/ReleaseAttempts"] = (
            self.engine.generator_release_attempts
        )
        load_fresh = self.engine.generator_load_fresh(now)
        unloaded_ready, unloaded_reason = (
            self.engine.generator_unload_interlock(now)
        )
        self.genset["/Foretravel/Control/GeneratorSourceConfirmed"] = int(
            self.engine.generator_source_confirmed
        )
        self.genset["/Foretravel/Control/InputCurrentFresh"] = int(load_fresh)
        self.genset["/Foretravel/Control/InputL1Current"] = (
            self.engine.generator_input_l1_current if load_fresh else None
        )
        self.genset["/Foretravel/Control/InputL2Current"] = (
            self.engine.generator_input_l2_current if load_fresh else None
        )
        self.genset["/Foretravel/Control/InputTotalCurrent"] = (
            self.engine.generator_input_total_current if load_fresh else None
        )
        self.genset["/Foretravel/Control/UnloadedThresholdAmps"] = (
            self.config.generator_unloaded_current_threshold_amps
        )
        self.genset["/Foretravel/Control/UnloadedInterlockReady"] = int(
            unloaded_ready
        )
        self.genset["/Foretravel/Control/UnloadedInterlockReason"] = (
            unloaded_reason
        )
        confirm_remaining = None
        if self.engine.generator_unloaded_since is not None:
            confirm_remaining = max(
                0.0,
                self.config.generator_unloaded_confirm_seconds
                - (now - self.engine.generator_unloaded_since),
            )
        self.genset[
            "/Foretravel/Control/UnloadedConfirmRemainingSeconds"
        ] = confirm_remaining
        for path, deadline in (
            (
                "/Foretravel/Control/KeepaliveRemainingSeconds",
                self.engine.generator_keepalive_at,
            ),
            (
                "/Foretravel/Control/StartRemainingSeconds",
                self.engine.generator_start_deadline,
            ),
            (
                "/Foretravel/Control/CooldownRemainingSeconds",
                self.engine.generator_cooldown_deadline,
            ),
            (
                "/Foretravel/Control/MaxRunRemainingSeconds",
                self.engine.generator_max_run_deadline,
            ),
            (
                "/Foretravel/Control/StopEscalationRemainingSeconds",
                self.engine.generator_stop_escalation_deadline,
            ),
        ):
            self.genset[path] = (
                None if deadline is None else max(0.0, deadline - now)
            )
        any_fresh = any(
            fresh(kind, now)
            for kind in (
                MessageKind.GENERATOR_DEMAND_STATUS,
                MessageKind.GENERATOR_STATUS_1,
            )
        )
        self.genset["/Connected"] = int(any_fresh)

        channel_values = {
            "water_pump": (
                snapshot.pump_on,
                fresh(MessageKind.WATER_PUMP_STATUS, now),
            ),
            "autofill": (
                snapshot.autofill_operating,
                fresh(MessageKind.AUTOFILL_STATUS, now),
            ),
            "generator": (
                self.engine._generator_running(),
                fresh(MessageKind.GENERATOR_STATUS_1, now),
            ),
        }
        for name, (actual, is_fresh) in channel_values.items():
            channel = self.CHANNELS[name]
            base = "/SwitchableOutput/{}/".format(channel)
            requested = self.engine.views[name].requested
            self.switch[base + "State"] = int(bool(requested))
            self.switch[base + "Status"] = self._switch_status(
                name, actual, is_fresh
            )

        pump_fresh = fresh(MessageKind.WATER_PUMP_STATUS, now)
        self.switch["/Foretravel/Pump/Stale"] = int(not pump_fresh)
        self.switch["/Foretravel/Pump/Fault"] = (
            self.engine.views["water_pump"].fault
        )
        if not pump_fresh:
            for leaf in (
                "Operating",
                "Running",
                "WaterHookupDetected",
                "SystemPressurePa",
                "SystemPressurePsi",
                "PumpPressureSettingPa",
                "PumpPressureSettingPsi",
                "RegulatorPressureSettingPa",
                "RegulatorPressureSettingPsi",
                "OperatingCurrentAmps",
            ):
                self.switch["/Foretravel/Pump/" + leaf] = None

        autofill_fresh = fresh(MessageKind.AUTOFILL_STATUS, now)
        self.switch["/Foretravel/Autofill/Stale"] = int(
            not autofill_fresh
        )
        self.switch["/Foretravel/Autofill/Fault"] = (
            self.engine.views["autofill"].fault
        )
        ready, reason = self.engine.autofill_start_interlock(now=now)
        self.switch["/Foretravel/Autofill/InterlockReady"] = int(ready)
        self.switch["/Foretravel/Autofill/InterlockReason"] = reason
        deadline = self.engine.autofill_max_run_deadline
        self.switch["/Foretravel/Autofill/RemainingMaxRunSeconds"] = (
            None if deadline is None else max(0.0, deadline - now)
        )
        if not autofill_fresh:
            self.switch["/Foretravel/Autofill/Operating"] = None
            self.switch["/Foretravel/Autofill/ValveOpen"] = None

        for instance, name in (
            (0, "Fresh"),
            (1, "Black"),
            (2, "Gray"),
            (3, "Lpg"),
        ):
            tank_fresh = self.engine._fresh_tank(instance, now)
            base = "/Foretravel/Tank/{}/".format(name)
            self.switch[base + "Stale"] = int(not tank_fresh)
            if not tank_fresh:
                for leaf in (
                    "LevelPercent",
                    "Resolution",
                    "AbsoluteLevelLiters",
                    "TankSizeLiters",
                ):
                    self.switch[base + leaf] = None

        if not fresh(MessageKind.GENERATOR_STATUS_1, now):
            for path in (
                "/StatusCode",
                "/Engine/OperatingHours",
                "/Engine/Load",
                "/StarterVoltage",
            ):
                self.genset[path] = None
        if not fresh(MessageKind.GENERATOR_STATUS_2, now):
            self.genset["/Engine/Speed"] = None
            self.genset["/Engine/CoolantTemperature"] = None
        # Generator AC normally updates much faster than the five-second
        # status messages, so use the two-second architecture limit.
        gen_ac_seen = snapshot.last_seen.get(MessageKind.GENERATOR_AC_STATUS_1)
        if gen_ac_seen is None or now - gen_ac_seen > 2.0:
            for path in (
                "/Ac/Frequency",
                "/Ac/Power",
                "/Ac/L1/Voltage",
                "/Ac/L1/Current",
                "/Ac/L1/Power",
                "/Ac/L2/Voltage",
                "/Ac/L2/Current",
                "/Ac/L2/Power",
            ):
                self.genset[path] = None

        for instance, service in self.temperature_services.items():
            seen = snapshot.ambient_temperature_seen.get(instance)
            temperature = snapshot.ambient_temperatures_c.get(instance)
            is_fresh = (
                seen is not None
                and now - seen <= self.config.status_max_age_seconds
                and temperature is not None
            )
            service["/Connected"] = int(is_fresh)
            service["/Temperature"] = temperature if is_fresh else None
