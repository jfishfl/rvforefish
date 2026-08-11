"""Decode the SilverLeaf messages needed by the integration.

Only fields supported by the TM-102 application manual are interpreted.  Raw
payloads remain attached so later captures can be reviewed without data loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from .can import CanFrame


TM102_SOURCE = 0xFA

DGN_GENERATOR_DEMAND_STATUS = 0x1FF80
DGN_GENERATOR_DEMAND_COMMAND = 0x1FEFF
DGN_AGS_CRITERION_STATUS = 0x1FEFE
DGN_AGS_CRITERION_COMMAND = 0x1FEFD
DGN_AGS_CRITERION_STATUS_2 = 0x1FED2
# The 2016 TM-102 document predates the final RVIA assignment for Status 2.
# Firmware from that era temporarily used 0x17003; observe both assignments.
DGN_TM102_LEGACY_AGS_CRITERION_STATUS_2 = 0x17003
DGN_AGS_DEMAND_CONFIGURATION_STATUS = 0x1FED5
DGN_LEGACY_GENERATOR_DEMAND_CONFIGURATION_STATUS = 0x1FEE7
DGN_GENERATOR_AC_STATUS_1 = 0x1FFDF
DGN_GENERATOR_STATUS_1 = 0x1FFDC
DGN_GENERATOR_STATUS_2 = 0x1FFDB
DGN_GENERATOR_START_CONFIG_STATUS = 0x1FFD9
DGN_ATS_AC_STATUS_1 = 0x1FFAD
DGN_ATS_STATUS = 0x1FFAA
DGN_TANK_STATUS = 0x1FFB7
DGN_WATER_PUMP_STATUS = 0x1FFB3
DGN_WATER_PUMP_COMMAND = 0x1FFB2
DGN_AUTOFILL_STATUS = 0x1FFB1
DGN_AUTOFILL_COMMAND = 0x1FFB0
DGN_THERMOSTAT_AMBIENT_STATUS = 0x1FF9C
DGN_INVERTER_COMMAND = 0x1FFD3
DGN_CHARGER_COMMAND = 0x1FFC5
DGN_CHARGER_CONFIGURATION_COMMAND = 0x1FFC4
DGN_CHARGER_CONFIGURATION_COMMAND_2 = 0x1FF95
PGN_J1939_REQUEST = 0x0EA00
# TM-102 proprietary destination-specific reports.  Only the documented AGS
# report operation bytes are decoded; all other proprietary traffic is ignored.
PGN_TM102_PROPRIETARY = 0x0EF00

SUPPORTED_DGNS = frozenset(
    {
        DGN_GENERATOR_DEMAND_STATUS,
        DGN_GENERATOR_DEMAND_COMMAND,
        DGN_AGS_CRITERION_STATUS,
        DGN_AGS_CRITERION_COMMAND,
        DGN_AGS_CRITERION_STATUS_2,
        DGN_TM102_LEGACY_AGS_CRITERION_STATUS_2,
        DGN_AGS_DEMAND_CONFIGURATION_STATUS,
        DGN_LEGACY_GENERATOR_DEMAND_CONFIGURATION_STATUS,
        DGN_GENERATOR_AC_STATUS_1,
        DGN_GENERATOR_STATUS_1,
        DGN_GENERATOR_STATUS_2,
        DGN_GENERATOR_START_CONFIG_STATUS,
        DGN_ATS_AC_STATUS_1,
        DGN_ATS_STATUS,
        DGN_TANK_STATUS,
        DGN_WATER_PUMP_STATUS,
        DGN_WATER_PUMP_COMMAND,
        DGN_AUTOFILL_STATUS,
        DGN_AUTOFILL_COMMAND,
        DGN_THERMOSTAT_AMBIENT_STATUS,
        DGN_INVERTER_COMMAND,
        DGN_CHARGER_COMMAND,
        DGN_CHARGER_CONFIGURATION_COMMAND,
        DGN_CHARGER_CONFIGURATION_COMMAND_2,
        PGN_TM102_PROPRIETARY,
    }
)


class MessageKind(str, Enum):
    REQUEST = "request"
    GENERATOR_DEMAND_STATUS = "generator_demand_status"
    GENERATOR_DEMAND_COMMAND = "generator_demand_command"
    AGS_CRITERION_STATUS = "ags_criterion_status"
    AGS_CRITERION_COMMAND = "ags_criterion_command"
    AGS_CRITERION_STATUS_2 = "ags_criterion_status_2"
    AGS_DEMAND_CONFIGURATION_STATUS = "ags_demand_configuration_status"
    GENERATOR_START_CONFIG_STATUS = "generator_start_config_status"
    TM102_AGS_STOP_STATUS = "tm102_ags_stop_status"
    TM102_AGS_STOP_LIMIT_STATUS = "tm102_ags_stop_limit_status"
    TM102_AUTOFILL_CONFIG_STATUS = "tm102_autofill_config_status"
    TM102_WATER_PUMP_CONFIG_STATUS = "tm102_water_pump_config_status"
    GENERATOR_STATUS_1 = "generator_status_1"
    GENERATOR_STATUS_2 = "generator_status_2"
    GENERATOR_AC_STATUS_1 = "generator_ac_status_1"
    ATS_STATUS = "ats_status"
    ATS_AC_STATUS_1 = "ats_ac_status_1"
    WATER_PUMP_STATUS = "water_pump_status"
    WATER_PUMP_COMMAND = "water_pump_command"
    AUTOFILL_STATUS = "autofill_status"
    AUTOFILL_COMMAND = "autofill_command"
    TANK_STATUS = "tank_status"
    THERMOSTAT_AMBIENT_STATUS = "thermostat_ambient_status"
    INVERTER_COMMAND = "inverter_command"
    CHARGER_COMMAND = "charger_command"
    CHARGER_CONFIGURATION_COMMAND = "charger_configuration_command"
    CHARGER_CONFIGURATION_COMMAND_2 = "charger_configuration_command_2"


@dataclass(frozen=True)
class DecodedMessage:
    kind: MessageKind
    frame: CanFrame
    fields: Dict[str, Any]


def _two_bit(byte: int, offset: int) -> Optional[bool]:
    value = (byte >> offset) & 0x3
    if value == 0:
        return False
    if value == 1:
        return True
    return None


def _u16_le(data: bytes, start: int) -> int:
    return int.from_bytes(data[start : start + 2], "little")


def _u32_le(data: bytes, start: int) -> int:
    return int.from_bytes(data[start : start + 4], "little")


def _voltage(raw: int) -> Optional[float]:
    # RV-C standard physical-unit table: uint16 volts, 0.050 V/bit.
    return None if raw == 0xFFFF else raw * 0.05


def _current(raw: int) -> Optional[float]:
    # RV-C standard physical-unit table: signed current is offset so 0x7D00
    # represents zero, with 0.05 A/bit.
    return None if raw == 0xFFFF else (raw - 0x7D00) * 0.05


def _frequency(raw: int) -> Optional[float]:
    return None if raw == 0xFFFF else raw / 128.0


def _pressure(raw: int) -> Optional[float]:
    # RV-C 2026 table 6.29.2b: uint16 pressure, 100 Pa/bit.
    # 0xFFFE is the standard error/out-of-range sentinel and 0xFFFF is
    # unavailable; neither may become a plausible high-pressure reading.
    return None if raw >= 0xFFFE else raw * 100.0


def _pressure_psi(raw: int) -> Optional[float]:
    pressure_pa = _pressure(raw)
    return None if pressure_pa is None else pressure_pa / 6894.757293168


def _percent_u8(raw: int) -> Optional[float]:
    return None if raw > 250 else raw * 0.5


def _temperature_u8(raw: int) -> Optional[float]:
    return None if raw > 250 else float(raw - 40)


def _temperature_u16(raw: int) -> Optional[float]:
    # RV-C 2026 table 5.3: uint16 temperature is offset by -273 C with
    # 0.03125 C/bit precision.  0xFFFE/0xFFFF are observed as invalid/no-data
    # sentinel values on this coach and must never become extreme readings.
    return None if raw >= 0xFFFE else raw * 0.03125 - 273.0


def _rpm(raw: int) -> Optional[float]:
    return None if raw == 0xFFFF else raw * 0.125


def _duration_u8(raw: int, *, scale: float) -> Optional[float]:
    return None if raw >= 0xFE else raw * scale


def _ags_criterion_name(instance: int, criterion_type: int) -> str:
    tm102_names = {
        1: "house_dc_voltage",
        2: "dc_voltage_or_charge_bridge",
        3: "ambient_temperature",
        4: "ats_ac_voltage",
        5: "dc_voltage_topoff",
        6: "scheduled_exercise",
        7: "external_gen_switch",
        8: "external_gen_demand",
        9: "house_dc_state_of_charge",
        10: "dc_state_of_charge_topoff",
        11: "quiet_time",
    }
    if instance in tm102_names:
        return tm102_names[instance]
    return {
        0: "dc_voltage",
        1: "dc_state_of_charge",
        2: "dc_current",
        3: "ambient_temperature",
        4: "ats_ac_voltage",
        5: "quiet_time",
        6: "timed_start",
        7: "air_conditioning",
        247: "proprietary_soc_topoff",
        248: "proprietary_external_input",
        249: "proprietary_scheduled_exercise",
        250: "proprietary_voltage_topoff",
    }.get(criterion_type, "proprietary_or_unknown")


def _decode_ags_criterion(data: bytes, *, source: int) -> Dict[str, Any]:
    """Decode standard RV-C criteria plus documented TM-102 extensions.

    The current RVIA definition uses 0.1 minute (6 second) units for the
    threshold timer.  TM-102 firmware explicitly documents a 5 second unit,
    so source 0xFA is decoded with that legacy scale rather than silently
    reporting a 20 percent timing error.
    """

    instance = data[0]
    criterion_type = data[2]
    fields: Dict[str, Any] = {
        "instance": instance,
        "demand": _two_bit(data[1], 0),
        "active": _two_bit(data[1], 2),
        "criterion_type": criterion_type,
        "criterion_name": _ags_criterion_name(instance, criterion_type),
    }
    delay_scale = 5.0 if source == TM102_SOURCE else 6.0

    if criterion_type == 0:
        threshold = _u16_le(data, 4)
        fields.update(
            monitored_instance=data[3],
            threshold_raw=threshold,
            threshold=_voltage(threshold),
            delay_seconds=_duration_u8(data[6], scale=delay_scale),
        )
    elif criterion_type == 1:
        fields.update(
            monitored_instance=data[3],
            start_threshold=_percent_u8(data[4]),
            stop_threshold=_percent_u8(data[5]),
            delay_seconds=_duration_u8(data[6], scale=delay_scale),
        )
    elif criterion_type == 2:
        threshold = _u16_le(data, 4)
        fields.update(
            monitored_instance=data[3],
            threshold_raw=threshold,
            threshold=_current(threshold),
            delay_seconds=_duration_u8(data[6], scale=delay_scale),
        )
    elif criterion_type == 3:
        threshold = _u16_le(data, 4)
        fields.update(
            monitored_instance=data[3],
            threshold_raw=threshold,
            threshold=_temperature_u16(threshold),
            delay_seconds=_duration_u8(data[6], scale=delay_scale),
        )
        if source == TM102_SOURCE:
            fields["deadband"] = _duration_u8(data[7], scale=0.1)
    elif criterion_type == 4:
        threshold = _u16_le(data, 4)
        fields.update(
            monitored_instance=data[3],
            threshold_raw=threshold,
            threshold=_voltage(threshold),
            delay_seconds=_duration_u8(data[6], scale=delay_scale),
        )
    elif criterion_type == 5:
        fields.update(
            begin_hour=None if data[4] > 23 else data[4],
            begin_minute=None if data[5] > 59 else data[5],
            end_hour=None if data[6] > 23 else data[6],
            end_minute=None if data[7] > 59 else data[7],
        )
    elif criterion_type == 6:
        run_time = _u16_le(data, 6)
        fields.update(
            begin_hour=None if data[4] > 23 else data[4],
            begin_minute=None if data[5] > 59 else data[5],
            run_time_minutes=None if run_time >= 0xFFFE else run_time,
        )
    elif criterion_type == 7:
        fields["monitored_instance"] = (
            None if data[3] > 250 else data[3]
        )
    elif criterion_type == 247:
        fields.update(
            monitored_instance=data[3],
            start_threshold=_percent_u8(data[4]),
            run_time_minutes=_duration_u8(data[6], scale=1.0),
        )
    elif criterion_type == 248:
        fields["input_delay_seconds"] = (
            _duration_u8(data[3], scale=0.25) if instance == 7 else 5.0
        )
    elif criterion_type == 249:
        day_states = (
            _two_bit(data[3], 0),
            _two_bit(data[3], 2),
            _two_bit(data[3], 4),
            _two_bit(data[3], 6),
            _two_bit(data[4], 0),
            _two_bit(data[4], 2),
            _two_bit(data[4], 4),
        )
        day_mask = sum(
            (1 << index) for index, enabled in enumerate(day_states) if enabled
        )
        fields.update(
            day_mask=day_mask,
            begin_hour=None if data[5] > 23 else data[5],
            begin_minute=None if data[6] > 59 else data[6],
            run_time_minutes=_duration_u8(data[7], scale=5.0),
        )
    elif criterion_type == 250:
        threshold = _u16_le(data, 4)
        fields.update(
            monitored_instance=data[3],
            threshold_raw=threshold,
            threshold=_voltage(threshold),
            run_time_minutes=_duration_u8(data[6], scale=1.0),
        )

    return fields


def _require_8(frame: CanFrame) -> None:
    if len(frame.data) != 8:
        raise ValueError(
            "DGN 0x{:05X} expected 8 bytes, got {}".format(
                frame.dgn, len(frame.data)
            )
        )


def decode_frame(frame: CanFrame) -> Optional[DecodedMessage]:
    # REQUEST is a PDU1 message.  ``frame.dgn`` contains the destination in
    # its low byte for PDU1 frames, so compare the canonical PGN instead.
    if frame.canonical_pgn == PGN_J1939_REQUEST:
        if len(frame.data) < 3:
            raise ValueError("J1939 REQUEST requires a three-byte PGN")
        requested_pgn = int.from_bytes(frame.data[:3], "little") & 0x3FFFF
        return DecodedMessage(
            kind=MessageKind.REQUEST,
            frame=frame,
            fields={
                "requested_pgn": requested_pgn,
                "destination": frame.destination,
                "global": frame.destination == 0xFF,
                "raw": frame.data.hex().upper(),
            },
        )

    if frame.canonical_pgn == PGN_TM102_PROPRIETARY:
        if len(frame.data) != 8:
            raise ValueError("TM-102 proprietary report requires eight bytes")
        data = frame.data
        operation = data[0]
        if operation == 0xEF:
            max_run = _u16_le(data, 1)
            plus_time = _u16_le(data, 6)
            fields = {
                "operation": operation,
                "maximum_run_minutes": (
                    None if max_run >= 0xFFFE else max_run
                ),
                "stop_criterion": data[3] & 0x0F,
                "disable_on_movement": _two_bit(data[3], 4),
                "main_charger_instance": (
                    None if data[4] == 0xFF else data[4]
                ),
                "second_charger_instance": (
                    None if data[5] == 0xFF else data[5]
                ),
                "plus_time_minutes": (
                    None if plus_time >= 0xFFFE else plus_time
                ),
                "destination": frame.destination,
                "raw": data.hex().upper(),
            }
            return DecodedMessage(
                MessageKind.TM102_AGS_STOP_STATUS, frame, fields
            )
        if operation == 0x7F:
            max_limit = _u16_le(data, 1)
            fields = {
                "operation": operation,
                "maximum_run_limit_minutes": (
                    None if max_limit >= 0xFFFE else max_limit
                ),
                "destination": frame.destination,
                "raw": data.hex().upper(),
            }
            return DecodedMessage(
                MessageKind.TM102_AGS_STOP_LIMIT_STATUS, frame, fields
            )
        if operation == 0xED:
            fields = {
                "operation": operation,
                "cutoff_level_percent": _percent_u8(data[1]),
                "run_after_seconds": _duration_u8(data[2], scale=1.0),
                "timeout_minutes": _duration_u8(data[3], scale=1.0),
                "auto_start_level_percent": _percent_u8(data[4]),
                "pump_on_cancels_fill": _two_bit(data[5], 0),
                "pump_bypass_disables_fill": _two_bit(data[5], 2),
                "ignore_pump": _two_bit(data[5], 4),
                "check_water_pressure": _two_bit(data[5], 6),
                "extended_run_after_minutes": _duration_u8(
                    data[6], scale=1.0
                ),
                "black_tank_warning_percent": _percent_u8(data[7]),
                "destination": frame.destination,
                "raw": data.hex().upper(),
            }
            return DecodedMessage(
                MessageKind.TM102_AUTOFILL_CONFIG_STATUS, frame, fields
            )
        if operation == 0xD4:
            implementation = data[3]
            fields = {
                "operation": operation,
                "input_switch_constant_demand": _two_bit(data[1], 0),
                "output_relay_latching": _two_bit(data[1], 2),
                "bypass_detect_enabled": _two_bit(data[2], 0),
                "implementation_raw": implementation,
                "implementation": {
                    0: "internal",
                    1: "external_dc_load",
                    2: "external_dc_dimmer",
                    3: "external_water_pump",
                }.get(implementation, "unknown"),
                "external_rvc_instance": (
                    None if data[4] == 0xFF else data[4]
                ),
                "destination": frame.destination,
                "raw": data.hex().upper(),
            }
            return DecodedMessage(
                MessageKind.TM102_WATER_PUMP_CONFIG_STATUS, frame, fields
            )
        return None

    dgn = frame.dgn
    if dgn not in SUPPORTED_DGNS:
        return None

    _require_8(frame)
    data = frame.data

    if dgn == DGN_GENERATOR_DEMAND_STATUS:
        fields = {
            "demand": _two_bit(data[0], 0),
            "internal_demand": _two_bit(data[0], 2),
            "network_demand": _two_bit(data[0], 4),
            "external_activity": _two_bit(data[0], 6),
            "manual_override": _two_bit(data[1], 0),
            "quiet_time": _two_bit(data[1], 2),
            "quiet_time_override": _two_bit(data[1], 4),
            "generator_lock": _two_bit(data[1], 6),
            "minimum_cycle_time_raw": data[6],
        }
        kind = MessageKind.GENERATOR_DEMAND_STATUS
    elif dgn == DGN_GENERATOR_DEMAND_COMMAND:
        fields = {
            "demand": _two_bit(data[0], 0),
            "quiet_time_override": _two_bit(data[0], 2),
            "external_activity_reset": _two_bit(data[0], 4),
            "manual_override": _two_bit(data[0], 6),
            "generator_lock": _two_bit(data[1], 0),
            "minimum_cycle_time_raw": data[6],
        }
        kind = MessageKind.GENERATOR_DEMAND_COMMAND
    elif dgn in {DGN_AGS_CRITERION_STATUS, DGN_AGS_CRITERION_COMMAND}:
        fields = _decode_ags_criterion(data, source=frame.source)
        if dgn == DGN_AGS_CRITERION_COMMAND:
            fields["command"] = (data[1] >> 0) & 0x03
            # Byte 1 bits 0..1 are command rather than demand in the command
            # DGN.  Remove the status-only interpretation to prevent misuse.
            fields.pop("demand", None)
            kind = MessageKind.AGS_CRITERION_COMMAND
        else:
            kind = MessageKind.AGS_CRITERION_STATUS
    elif dgn in {
        DGN_AGS_CRITERION_STATUS_2,
        DGN_TM102_LEGACY_AGS_CRITERION_STATUS_2,
    }:
        counter = _u16_le(data, 2)
        fields = {
            "instance": data[0],
            "criterion_type": data[1],
            "criterion_name": _ags_criterion_name(data[0], data[1]),
            "counter_seconds": None if counter >= 0xFFFE else counter,
            "legacy_dgn": dgn == DGN_TM102_LEGACY_AGS_CRITERION_STATUS_2,
        }
        kind = MessageKind.AGS_CRITERION_STATUS_2
    elif dgn in {
        DGN_AGS_DEMAND_CONFIGURATION_STATUS,
        DGN_LEGACY_GENERATOR_DEMAND_CONFIGURATION_STATUS,
    }:
        fields = {
            "disable_on_park_brake_release": _two_bit(data[0], 0),
            "disable_on_ignition": _two_bit(data[0], 2),
            "disable_on_drive": _two_bit(data[0], 4),
            "disable_on_motion": _two_bit(data[0], 6),
            "disable_on_oem_switch": _two_bit(data[1], 0),
            "disable_on_service_brake": _two_bit(data[1], 2),
            "disable_on_carbon_monoxide": _two_bit(data[1], 4),
            "disable_on_opened_compartment": _two_bit(data[1], 6),
            "disable_on_fire_alarm": _two_bit(data[2], 0),
            "disable_on_manual_operation": _two_bit(data[2], 2),
            "disable_on_genset_fault": _two_bit(data[2], 4),
            "disable_on_system_fault": _two_bit(data[2], 6),
            "disable_on_shore_power": _two_bit(data[3], 0),
            "disable_on_50_amp_shore": _two_bit(data[3], 2),
            "disable_after_days": None if data[4] > 250 else data[4],
            "days_remaining": None if data[5] > 250 else data[5],
            "legacy_dgn": (
                dgn == DGN_LEGACY_GENERATOR_DEMAND_CONFIGURATION_STATUS
            ),
        }
        kind = MessageKind.AGS_DEMAND_CONFIGURATION_STATUS
    elif dgn == DGN_GENERATOR_START_CONFIG_STATUS:
        fields = {
            "generator_type": None if data[0] == 0xFF else data[0],
            "pre_crank_seconds": None if data[1] > 250 else data[1],
            "maximum_crank_seconds": None if data[2] > 250 else data[2],
            "stop_seconds": None if data[3] > 250 else data[3],
        }
        kind = MessageKind.GENERATOR_START_CONFIG_STATUS
    elif dgn == DGN_GENERATOR_STATUS_1:
        starter_raw = _u16_le(data, 6)
        fields = {
            "status_raw": data[0],
            "status": {
                0: "stopped",
                1: "preheat",
                2: "cranking",
                3: "running",
                4: "priming",
                5: "fault",
                6: "engine_run_only",
                7: "test_mode",
                8: "voltage_adjust",
                9: "fault_bypass",
                10: "configuration",
            }.get(data[0], "unknown"),
            "runtime_minutes": _u32_le(data, 1),
            "engine_load_raw": data[5],
            "engine_load_percent": _percent_u8(data[5]),
            "start_battery_voltage_raw": starter_raw,
            "start_battery_voltage": _voltage(starter_raw),
        }
        kind = MessageKind.GENERATOR_STATUS_1
    elif dgn == DGN_GENERATOR_STATUS_2:
        rpm_raw = _u16_le(data, 3)
        fields = {
            "temperature_shutdown": _two_bit(data[0], 0),
            "oil_pressure_shutdown": _two_bit(data[0], 2),
            "caution": _two_bit(data[0], 6),
            "coolant_temperature_raw": data[1],
            "coolant_temperature": _temperature_u8(data[1]),
            "engine_rpm_raw": rpm_raw,
            "engine_rpm": _rpm(rpm_raw),
        }
        kind = MessageKind.GENERATOR_STATUS_2
    elif dgn == DGN_GENERATOR_AC_STATUS_1:
        voltage_raw = _u16_le(data, 1)
        current_raw = _u16_le(data, 3)
        frequency_raw = _u16_le(data, 5)
        fields = {
            "instance": data[0],
            "generator_instance": (data[0] >> 4) & 0x0F,
            "line_instance": data[0] & 0x0F,
            "voltage_raw": voltage_raw,
            "voltage": _voltage(voltage_raw),
            "current_raw": current_raw,
            "current": _current(current_raw),
            "frequency_raw": frequency_raw,
            "frequency": _frequency(frequency_raw),
        }
        kind = MessageKind.GENERATOR_AC_STATUS_1
    elif dgn == DGN_ATS_STATUS:
        source_raw = data[1]
        source = {0: "generator", 1: "shore", 253: "none"}.get(
            source_raw, "unknown"
        )
        fields = {
            "instance": data[0],
            "transfer_switch_instance": (data[0] >> 4) & 0x0F,
            "line_instance": data[0] & 0x0F,
            "source_raw": source_raw,
            "source": source,
            "mode": _two_bit(data[2], 0),
        }
        kind = MessageKind.ATS_STATUS
    elif dgn == DGN_ATS_AC_STATUS_1:
        voltage_raw = _u16_le(data, 1)
        current_raw = _u16_le(data, 3)
        frequency_raw = _u16_le(data, 5)
        fields = {
            "instance": data[0],
            "voltage_raw": voltage_raw,
            "voltage": _voltage(voltage_raw),
            "current_raw": current_raw,
            "current": _current(current_raw),
            "frequency_raw": frequency_raw,
            "frequency": _frequency(frequency_raw),
            "faults_raw": data[7],
        }
        kind = MessageKind.ATS_AC_STATUS_1
    elif dgn == DGN_WATER_PUMP_STATUS:
        pressure_raw = _u16_le(data, 1)
        pump_pressure_raw = _u16_le(data, 3)
        regulator_pressure_raw = _u16_le(data, 5)
        fields = {
            "on": _two_bit(data[0], 0),
            "running": _two_bit(data[0], 2),
            "water_hookup_detected": _two_bit(data[0], 4),
            "pressure_raw": pressure_raw,
            "pressure_pa": _pressure(pressure_raw),
            "pressure_psi": _pressure_psi(pressure_raw),
            "pump_pressure_setting_raw": pump_pressure_raw,
            "pump_pressure_setting_pa": _pressure(pump_pressure_raw),
            "pump_pressure_setting_psi": _pressure_psi(pump_pressure_raw),
            "regulator_pressure_setting_raw": regulator_pressure_raw,
            "regulator_pressure_setting_pa": _pressure(
                regulator_pressure_raw
            ),
            "regulator_pressure_setting_psi": _pressure_psi(
                regulator_pressure_raw
            ),
            "operating_current_amps": (
                # Table 5.3 bounds uint8 amperage at 250 A.  Values above
                # that range are reserved/sentinel values.
                None if data[7] > 250 else float(data[7])
            ),
        }
        kind = MessageKind.WATER_PUMP_STATUS
    elif dgn == DGN_WATER_PUMP_COMMAND:
        fields = {"on": _two_bit(data[0], 0)}
        kind = MessageKind.WATER_PUMP_COMMAND
    elif dgn == DGN_AUTOFILL_STATUS:
        last_operation_raw = (data[0] >> 4) & 0xF
        fields = {
            "operating": _two_bit(data[0], 0),
            "valve_open": _two_bit(data[0], 2),
            "last_operation_raw": last_operation_raw,
            "last_operation": {
                0: "running",
                1: "successful_fill",
                2: "timed_out",
                3: "manually_aborted",
                4: "aborted_due_to_error",
            }.get(last_operation_raw, "unknown"),
        }
        kind = MessageKind.AUTOFILL_STATUS
    elif dgn == DGN_AUTOFILL_COMMAND:
        fields = {
            "operating": _two_bit(data[0], 0),
            "manual_valve_open": _two_bit(data[0], 2),
        }
        kind = MessageKind.AUTOFILL_COMMAND
    elif dgn == DGN_THERMOSTAT_AMBIENT_STATUS:
        temperature_raw = _u16_le(data, 1)
        fields = {
            "instance": data[0],
            "temperature_raw": temperature_raw,
            "temperature_c": _temperature_u16(temperature_raw),
        }
        kind = MessageKind.THERMOSTAT_AMBIENT_STATUS
    elif dgn == DGN_INVERTER_COMMAND:
        fields = {
            "instance": data[0],
            "inverter_enable": _two_bit(data[1], 0),
            "load_sense_enable": _two_bit(data[1], 2),
            "passthrough_enable": _two_bit(data[1], 4),
            "generator_support_enable": _two_bit(data[1], 6),
            "inverter_enable_on_startup": _two_bit(data[7], 0),
        }
        kind = MessageKind.INVERTER_COMMAND
    elif dgn == DGN_CHARGER_COMMAND:
        voltage_raw = _u16_le(data, 3)
        current_raw = _u16_le(data, 5)
        fields = {
            "instance": data[0],
            "status_raw": data[1],
            "default_enabled": _two_bit(data[2], 0),
            "auto_recharge_enable": _two_bit(data[2], 2),
            "force_charge_raw": (data[2] >> 4) & 0x0F,
            "control_voltage_raw": voltage_raw,
            "control_voltage": _voltage(voltage_raw),
            "control_current_raw": current_raw,
            "control_current": _current(current_raw),
        }
        kind = MessageKind.CHARGER_COMMAND
    elif dgn == DGN_CHARGER_CONFIGURATION_COMMAND:
        bank_size_raw = _u16_le(data, 4)
        fields = {
            "instance": data[0],
            "charging_algorithm_raw": data[1],
            "charger_mode_raw": data[2],
            "battery_sensor_present": _two_bit(data[3], 0),
            "installation_line_raw": (data[3] >> 2) & 0x03,
            "battery_bank_size_raw": bank_size_raw,
            "battery_bank_size_ah": (
                None if bank_size_raw == 0xFFFF else bank_size_raw
            ),
            "battery_type_raw": data[6] & 0x0F,
            "maximum_charging_current": (
                None if data[7] == 0xFF else float(data[7])
            ),
        }
        kind = MessageKind.CHARGER_CONFIGURATION_COMMAND
    elif dgn == DGN_CHARGER_CONFIGURATION_COMMAND_2:
        recharge_raw = _u16_le(data, 5)
        fields = {
            "instance": data[0],
            "maximum_charge_percent": _percent_u8(data[1]),
            "charge_rate_limit_percent": _percent_u8(data[2]),
            "shore_breaker_size": (
                None if data[3] == 0xFF else float(data[3])
            ),
            "default_battery_temperature": _temperature_u8(data[4]),
            "recharge_voltage_raw": recharge_raw,
            "recharge_voltage": _voltage(recharge_raw),
        }
        kind = MessageKind.CHARGER_CONFIGURATION_COMMAND_2
    else:
        relative_raw = data[1]
        resolution = data[2]
        relative_percent = None
        if resolution not in {0, 0xFF} and relative_raw <= resolution:
            relative_percent = 100.0 * relative_raw / resolution
        absolute_raw = _u16_le(data, 3)
        size_raw = _u16_le(data, 5)
        fields = {
            "instance": data[0],
            "relative_level_raw": relative_raw,
            "resolution": resolution,
            "relative_level_percent": relative_percent,
            "absolute_level_liters": (
                None if absolute_raw > 65530 else absolute_raw
            ),
            "tank_size_liters": None if size_raw > 65530 else size_raw,
        }
        kind = MessageKind.TANK_STATUS

    fields["raw"] = data.hex().upper()
    return DecodedMessage(kind=kind, frame=frame, fields=fields)
