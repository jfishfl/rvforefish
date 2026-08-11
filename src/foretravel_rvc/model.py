"""Freshness-aware coach state and AC source classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

from .decode import DecodedMessage, MessageKind, TM102_SOURCE


class SourceClass(str, Enum):
    INVERTING = "inverting"
    SHORE = "shore"
    GENERATOR = "generator"
    GENERATOR_STARTING = "generator_starting"
    GENERATOR_NOT_ACCEPTED = "generator_not_accepted"
    AC_UNKNOWN = "ac_unknown"


@dataclass(frozen=True)
class SourceDecision:
    source: SourceClass
    reason: str
    safe_to_write_victron_label: bool


@dataclass
class TimedValue:
    value: object
    timestamp: float


@dataclass
class CoachSnapshot:
    pump_on: Optional[bool] = None
    pump_running: Optional[bool] = None
    water_hookup_detected: Optional[bool] = None
    water_pressure_pa: Optional[float] = None
    water_pressure_psi: Optional[float] = None
    pump_pressure_setting_pa: Optional[float] = None
    regulator_pressure_setting_pa: Optional[float] = None
    pump_operating_current_amps: Optional[float] = None
    water_pump_configuration: Dict[str, object] = field(default_factory=dict)
    autofill_operating: Optional[bool] = None
    autofill_valve_open: Optional[bool] = None
    autofill_last_operation_raw: Optional[int] = None
    autofill_last_operation: Optional[str] = None
    autofill_configuration: Dict[str, object] = field(default_factory=dict)
    tank_statuses: Dict[int, Dict[str, object]] = field(default_factory=dict)
    tank_seen: Dict[int, float] = field(default_factory=dict)
    generator_demand: Optional[bool] = None
    generator_internal_demand: Optional[bool] = None
    generator_network_demand: Optional[bool] = None
    generator_locked: Optional[bool] = None
    generator_external_activity: Optional[bool] = None
    generator_manual_override: Optional[bool] = None
    generator_quiet_time: Optional[bool] = None
    generator_quiet_time_override: Optional[bool] = None
    generator_minimum_cycle_minutes: Optional[int] = None
    generator_status_raw: Optional[int] = None
    generator_runtime_minutes: Optional[int] = None
    generator_ac_voltage: Optional[float] = None
    generator_ac_frequency: Optional[float] = None
    ats_source: Optional[str] = None
    ambient_temperatures_c: Dict[int, Optional[float]] = field(
        default_factory=dict
    )
    ambient_temperature_seen: Dict[int, float] = field(default_factory=dict)
    ags_criteria: Dict[int, Dict[str, object]] = field(default_factory=dict)
    ags_criterion_counters: Dict[int, Optional[int]] = field(
        default_factory=dict
    )
    ags_safety_configuration: Dict[str, object] = field(default_factory=dict)
    generator_start_configuration: Dict[str, object] = field(
        default_factory=dict
    )
    ags_stop_configuration: Dict[str, object] = field(default_factory=dict)
    last_seen: Dict[MessageKind, float] = field(default_factory=dict)


class StateReducer:
    def __init__(self, *, tm102_source: int = TM102_SOURCE) -> None:
        self.tm102_source = tm102_source
        self.snapshot = CoachSnapshot()

    def apply(self, message: DecodedMessage) -> CoachSnapshot:
        # Status authority is the TM-102. Commands from panels are still decoded
        # for audit, but cannot overwrite actual coach status.
        if message.frame.source != self.tm102_source:
            return self.snapshot

        fields = message.fields
        kind = message.kind
        self.snapshot.last_seen[kind] = message.frame.timestamp

        if kind == MessageKind.WATER_PUMP_STATUS:
            self.snapshot.pump_on = fields["on"]
            self.snapshot.pump_running = fields["running"]
            self.snapshot.water_hookup_detected = fields[
                "water_hookup_detected"
            ]
            self.snapshot.water_pressure_pa = fields["pressure_pa"]
            self.snapshot.water_pressure_psi = fields["pressure_psi"]
            self.snapshot.pump_pressure_setting_pa = fields[
                "pump_pressure_setting_pa"
            ]
            self.snapshot.regulator_pressure_setting_pa = fields[
                "regulator_pressure_setting_pa"
            ]
            self.snapshot.pump_operating_current_amps = fields[
                "operating_current_amps"
            ]
        elif kind == MessageKind.TM102_WATER_PUMP_CONFIG_STATUS:
            self.snapshot.water_pump_configuration = dict(fields)
        elif kind == MessageKind.AUTOFILL_STATUS:
            self.snapshot.autofill_operating = fields["operating"]
            self.snapshot.autofill_valve_open = fields["valve_open"]
            self.snapshot.autofill_last_operation_raw = fields[
                "last_operation_raw"
            ]
            self.snapshot.autofill_last_operation = fields["last_operation"]
        elif kind == MessageKind.TM102_AUTOFILL_CONFIG_STATUS:
            self.snapshot.autofill_configuration = dict(fields)
        elif kind == MessageKind.TANK_STATUS:
            instance = fields["instance"]
            self.snapshot.tank_statuses[instance] = dict(fields)
            self.snapshot.tank_seen[instance] = message.frame.timestamp
        elif kind == MessageKind.GENERATOR_DEMAND_STATUS:
            self.snapshot.generator_demand = fields["demand"]
            self.snapshot.generator_internal_demand = fields["internal_demand"]
            self.snapshot.generator_network_demand = fields["network_demand"]
            self.snapshot.generator_locked = fields["generator_lock"]
            self.snapshot.generator_external_activity = fields[
                "external_activity"
            ]
            self.snapshot.generator_manual_override = fields[
                "manual_override"
            ]
            self.snapshot.generator_quiet_time = fields["quiet_time"]
            self.snapshot.generator_quiet_time_override = fields[
                "quiet_time_override"
            ]
            minimum_cycle = fields["minimum_cycle_time_raw"]
            self.snapshot.generator_minimum_cycle_minutes = (
                None if minimum_cycle > 250 else minimum_cycle
            )
        elif kind == MessageKind.AGS_CRITERION_STATUS:
            self.snapshot.ags_criteria[fields["instance"]] = dict(fields)
        elif kind == MessageKind.AGS_CRITERION_STATUS_2:
            self.snapshot.ags_criterion_counters[fields["instance"]] = fields[
                "counter_seconds"
            ]
        elif kind == MessageKind.AGS_DEMAND_CONFIGURATION_STATUS:
            self.snapshot.ags_safety_configuration = dict(fields)
        elif kind == MessageKind.GENERATOR_START_CONFIG_STATUS:
            self.snapshot.generator_start_configuration = dict(fields)
        elif kind in {
            MessageKind.TM102_AGS_STOP_STATUS,
            MessageKind.TM102_AGS_STOP_LIMIT_STATUS,
        }:
            self.snapshot.ags_stop_configuration.update(fields)
        elif kind == MessageKind.GENERATOR_STATUS_1:
            self.snapshot.generator_status_raw = fields["status_raw"]
            self.snapshot.generator_runtime_minutes = fields["runtime_minutes"]
        elif kind == MessageKind.GENERATOR_AC_STATUS_1:
            self.snapshot.generator_ac_voltage = fields["voltage"]
            self.snapshot.generator_ac_frequency = fields["frequency"]
        elif kind == MessageKind.ATS_STATUS:
            self.snapshot.ats_source = fields["source"]
        elif kind == MessageKind.THERMOSTAT_AMBIENT_STATUS:
            instance = fields["instance"]
            self.snapshot.ambient_temperatures_c[instance] = fields[
                "temperature_c"
            ]
            self.snapshot.ambient_temperature_seen[instance] = (
                message.frame.timestamp
            )

        return self.snapshot


def classify_ac_source(
    *,
    ve_bus_accepting_ac: bool,
    active_input_voltage: Optional[float],
    generator_voltage: Optional[float],
    generator_frequency: Optional[float],
    ats_source: Optional[str],
    generator_demand: Optional[bool],
    ats_fresh: bool,
    generator_ac_fresh: bool,
    ve_bus_state_fresh: bool = True,
    valid_voltage: Tuple[float, float] = (105.0, 132.0),
    valid_frequency: Tuple[float, float] = (55.0, 65.0),
) -> SourceDecision:
    if not ve_bus_state_fresh:
        return SourceDecision(
            SourceClass.AC_UNKNOWN,
            "VE.Bus acceptance observation is unavailable or stale",
            False,
        )

    generator_ac_valid = (
        generator_ac_fresh
        and generator_voltage is not None
        and generator_frequency is not None
        and valid_voltage[0] <= generator_voltage <= valid_voltage[1]
        and valid_frequency[0] <= generator_frequency <= valid_frequency[1]
    )

    if generator_ac_valid and ats_fresh and ats_source == "generator":
        if ve_bus_accepting_ac and active_input_voltage is not None:
            return SourceDecision(
                SourceClass.GENERATOR,
                "fresh ATS and generator AC agree; VE.Bus accepted input",
                True,
            )
        return SourceDecision(
            SourceClass.GENERATOR_NOT_ACCEPTED,
            "generator power is valid at ATS but VE.Bus has not accepted it",
            False,
        )

    if ve_bus_accepting_ac and active_input_voltage is not None:
        if ats_fresh and ats_source == "shore":
            return SourceDecision(
                SourceClass.SHORE,
                "fresh ATS reports shore and VE.Bus accepted input",
                True,
            )
        return SourceDecision(
            SourceClass.AC_UNKNOWN,
            "VE.Bus accepted AC but authoritative ATS source is unavailable",
            False,
        )

    if generator_demand:
        return SourceDecision(
            SourceClass.GENERATOR_STARTING,
            "generator is demanded but no accepted, validated generator AC exists",
            False,
        )

    return SourceDecision(
        SourceClass.INVERTING,
        "VE.Bus is not accepting AC and no generator demand is active",
        True,
    )
