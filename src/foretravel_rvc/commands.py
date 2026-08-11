"""Safety-constrained RV-C command builders.

These builders do not transmit.  Runtime transmission remains disabled until a
live capture verifies the coach panel's payloads and the Cerbo RV-C NAD is
confirmed conflict-free.
"""

from __future__ import annotations

from .can import CanFrame
from .decode import (
    DGN_AUTOFILL_COMMAND,
    DGN_GENERATOR_DEMAND_COMMAND,
    DGN_WATER_PUMP_COMMAND,
)


# RV-C assigns priority 6 to GENERATOR_DEMAND_COMMAND and the other command
# DGNs emitted by this bridge.  Priority is part of the 29-bit CAN identifier;
# using zero would produce the right DGN after masking but the wrong wire ID.
DEFAULT_PRIORITY = 6


def extended_id(dgn: int, source: int, priority: int = DEFAULT_PRIORITY) -> int:
    if not 0 <= dgn <= 0x3FFFF:
        raise ValueError("DGN must fit in 18 bits")
    if not 0 <= source <= 0xFF:
        raise ValueError("source address must fit in one byte")
    if not 0 <= priority <= 7:
        raise ValueError("priority must be 0..7")
    return (priority << 26) | (dgn << 8) | source


def _frame(dgn: int, source: int, payload: bytes) -> CanFrame:
    return CanFrame(0.0, "vecan0", extended_id(dgn, source), payload)


def water_pump_command(source: int, on: bool) -> CanFrame:
    # Only the command field is supported.  All other fields are unavailable.
    first = 0xFD if on else 0xFC
    return _frame(DGN_WATER_PUMP_COMMAND, source, bytes([first]) + b"\xFF" * 7)


def autofill_command(source: int, on: bool) -> CanFrame:
    # Manual-valve control is deliberately left unavailable and must never be
    # exposed by the UI.  Autofill start is gated elsewhere by safety inputs.
    first = (0xF0 | (0x01 if on else 0x00) | 0x0C)
    return _frame(DGN_AUTOFILL_COMMAND, source, bytes([first]) + b"\xFF" * 7)


def generator_demand_command(
    source: int,
    demand: bool,
) -> CanFrame:
    """Build a cooperative demand, never a direct generator command.

    This bridge is an RV-C Network Demand Source, not a manual control panel.
    It therefore leaves quiet-time override, external-activity reset, manual
    override, generator lock, and Set External Activity in normal/no-action
    states.  The Total Coach panel's observed 0x5D/0x5C first byte is not copied:
    those frames intentionally assert Manual Override and clear external
    activity, which a network demand source must not do.
    """

    first = 0x01 if demand else 0x00
    # Generator-lock is normal (00), Set External Activity is 11 (no action),
    # and the remaining byte-1 fields are not defined.
    payload = bytes([first, 0xFC]) + b"\xFF" * 6
    return _frame(DGN_GENERATOR_DEMAND_COMMAND, source, payload)
