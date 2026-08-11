"""Low-volume, structured audit events for live validation."""

from __future__ import annotations

from typing import Dict, Tuple

from .can import CanFrame
from .decode import DGN_GENERATOR_DEMAND_COMMAND, DecodedMessage, MessageKind


COMMAND_KINDS = {
    MessageKind.WATER_PUMP_COMMAND,
    MessageKind.AUTOFILL_COMMAND,
    MessageKind.GENERATOR_DEMAND_COMMAND,
    MessageKind.INVERTER_COMMAND,
    MessageKind.CHARGER_COMMAND,
    MessageKind.CHARGER_CONFIGURATION_COMMAND,
    MessageKind.CHARGER_CONFIGURATION_COMMAND_2,
    MessageKind.AGS_CRITERION_COMMAND,
}

STATE_FIELDS = {
    MessageKind.WATER_PUMP_STATUS: (
        "on",
        "running",
        "water_hookup_detected",
        "pressure_psi",
    ),
    MessageKind.AUTOFILL_STATUS: (
        "operating",
        "valve_open",
        "last_operation_raw",
        "last_operation",
    ),
    MessageKind.TANK_STATUS: (
        "instance",
        "relative_level_percent",
        "resolution",
    ),
    MessageKind.TM102_AUTOFILL_CONFIG_STATUS: (
        "cutoff_level_percent",
        "timeout_minutes",
        "pump_on_cancels_fill",
        "pump_bypass_disables_fill",
        "check_water_pressure",
    ),
    MessageKind.TM102_WATER_PUMP_CONFIG_STATUS: (
        "input_switch_constant_demand",
        "output_relay_latching",
        "bypass_detect_enabled",
        "implementation",
        "external_rvc_instance",
    ),
    MessageKind.GENERATOR_DEMAND_STATUS: (
        "demand",
        "internal_demand",
        "network_demand",
        "external_activity",
        "manual_override",
        "quiet_time",
        "quiet_time_override",
        "generator_lock",
    ),
    MessageKind.GENERATOR_STATUS_1: ("status", "runtime_minutes"),
    MessageKind.GENERATOR_STATUS_2: (
        "temperature_shutdown",
        "oil_pressure_shutdown",
        "caution",
    ),
    MessageKind.GENERATOR_AC_STATUS_1: (
        "generator_instance",
        "line_instance",
        "voltage",
        "current",
        "frequency",
    ),
    MessageKind.ATS_STATUS: ("source", "mode"),
    MessageKind.THERMOSTAT_AMBIENT_STATUS: (
        "instance",
        "temperature_c",
    ),
    MessageKind.AGS_CRITERION_STATUS: (
        "instance",
        "demand",
        "active",
        "criterion_type",
        "criterion_name",
    ),
    MessageKind.AGS_CRITERION_STATUS_2: (
        "instance",
        "criterion_type",
        "counter_seconds",
        "legacy_dgn",
    ),
    MessageKind.AGS_DEMAND_CONFIGURATION_STATUS: (
        "disable_on_motion",
        "disable_on_carbon_monoxide",
        "disable_on_opened_compartment",
        "disable_on_manual_operation",
        "disable_on_genset_fault",
        "disable_on_shore_power",
        "legacy_dgn",
    ),
    MessageKind.GENERATOR_START_CONFIG_STATUS: (
        "generator_type",
        "pre_crank_seconds",
        "maximum_crank_seconds",
        "stop_seconds",
    ),
    MessageKind.TM102_AGS_STOP_STATUS: (
        "maximum_run_minutes",
        "stop_criterion",
        "disable_on_movement",
        "plus_time_minutes",
    ),
    MessageKind.TM102_AGS_STOP_LIMIT_STATUS: (
        "maximum_run_limit_minutes",
    ),
}


class AuditLogger:
    def __init__(self, logger, *, tm102_source: int = 0xFA) -> None:
        self.logger = logger
        self.tm102_source = tm102_source
        self._last: Dict[object, Tuple[object, ...]] = {}

    def observe(self, message: DecodedMessage) -> None:
        if message.kind in COMMAND_KINDS:
            self.logger.info(
                "AUDIT RX_COMMAND kind=%s src=0x%02X dgn=0x%05X data=%s",
                message.kind.value,
                message.frame.source,
                message.frame.dgn,
                message.fields["raw"],
            )
            return

        if (
            message.kind == MessageKind.REQUEST
            and message.fields["requested_pgn"] == DGN_GENERATOR_DEMAND_COMMAND
        ):
            destination = message.fields["destination"]
            self.logger.info(
                "AUDIT RX_REQUEST src=0x%02X dst=0x%02X requested=0x%05X data=%s",
                message.frame.source,
                destination,
                message.fields["requested_pgn"],
                message.fields["raw"],
            )
            return

        keys = STATE_FIELDS.get(message.kind)
        if keys is None:
            return
        if message.frame.source != self.tm102_source:
            return
        values = tuple(message.fields.get(key) for key in keys)
        if message.kind == MessageKind.GENERATOR_AC_STATUS_1:
            values = (
                values[0],
                values[1],
                None if values[2] is None else round(values[2]),
                None if values[3] is None else round(values[3]),
                None if values[4] is None else round(values[4], 1),
            )
        state_key: object = message.kind
        if message.kind == MessageKind.GENERATOR_AC_STATUS_1:
            state_key = (
                message.kind,
                message.fields["generator_instance"],
                message.fields["line_instance"],
            )
        elif message.kind == MessageKind.THERMOSTAT_AMBIENT_STATUS:
            state_key = (message.kind, message.fields["instance"])
            values = (
                values[0],
                None if values[1] is None else round(values[1], 1),
            )
        elif message.kind in {
            MessageKind.AGS_CRITERION_STATUS,
            MessageKind.AGS_CRITERION_STATUS_2,
        }:
            state_key = (message.kind, message.fields["instance"])
        elif message.kind == MessageKind.TANK_STATUS:
            state_key = (message.kind, message.fields["instance"])
        if self._last.get(state_key) == values:
            return
        self._last[state_key] = values
        details = " ".join(
            "{}={!r}".format(key, value) for key, value in zip(keys, values)
        )
        self.logger.info(
            "AUDIT STATE kind=%s src=0x%02X %s",
            message.kind.value,
            message.frame.source,
            details,
        )

    def transmit(self, frame: CanFrame) -> None:
        self.logger.warning(
            "AUDIT TX src=0x%02X dgn=0x%05X data=%s",
            frame.source,
            frame.dgn,
            frame.data.hex().upper(),
        )
