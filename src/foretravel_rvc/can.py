"""Minimal J1939/RV-C frame representation and candump parsing.

The runtime adapter will read Linux SocketCAN directly.  Keeping this module
free of D-Bus and GLib dependencies makes captures replayable on a workstation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional


_CANDUMP_RE = re.compile(
    r"^\((?P<timestamp>\d+(?:\.\d+)?)\)\s+"
    r"(?P<interface>\S+)\s+"
    r"(?P<can_id>[0-9A-Fa-f]{1,8})#(?P<data>[0-9A-Fa-f]*)$"
)


@dataclass(frozen=True)
class CanFrame:
    timestamp: float
    interface: str
    can_id: int
    data: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.can_id <= 0x1FFFFFFF:
            raise ValueError("RV-C uses a 29-bit extended CAN identifier")
        if len(self.data) > 8:
            raise ValueError("classic CAN payload cannot exceed 8 bytes")

    @property
    def priority(self) -> int:
        return (self.can_id >> 26) & 0x7

    @property
    def source(self) -> int:
        return self.can_id & 0xFF

    @property
    def data_page(self) -> int:
        return (self.can_id >> 24) & 0x1

    @property
    def pdu_format(self) -> int:
        return (self.can_id >> 16) & 0xFF

    @property
    def pdu_specific(self) -> int:
        return (self.can_id >> 8) & 0xFF

    @property
    def dgn(self) -> int:
        """RV-C DGN as carried in the 18 bits above source address."""

        return (self.can_id >> 8) & 0x3FFFF

    @property
    def canonical_pgn(self) -> int:
        """J1939 PGN with destination byte cleared for PDU1 frames."""

        base = (self.data_page << 16) | (self.pdu_format << 8)
        if self.pdu_format >= 240:
            base |= self.pdu_specific
        return base

    @property
    def destination(self) -> Optional[int]:
        return self.pdu_specific if self.pdu_format < 240 else None


def parse_candump_line(line: str) -> CanFrame:
    match = _CANDUMP_RE.fullmatch(line.strip())
    if not match:
        raise ValueError("unsupported candump line: {!r}".format(line.rstrip()))

    data_hex = match.group("data")
    if len(data_hex) % 2:
        raise ValueError("CAN payload must contain complete bytes")

    return CanFrame(
        timestamp=float(match.group("timestamp")),
        interface=match.group("interface"),
        can_id=int(match.group("can_id"), 16),
        data=bytes.fromhex(data_hex),
    )
