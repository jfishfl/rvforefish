"""Small SocketCAN transport with an immutable read-only mode."""

from __future__ import annotations

import socket
import struct
import time
from typing import Iterable, Optional

from .can import CanFrame


CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF
_CAN_FRAME = struct.Struct("=IB3x8s")
_CAN_FILTER = struct.Struct("=II")
CAN_RAW_FILTER = 1


def build_socketcan_filters(
    dgns: Iterable[int], *, include_j1939_request: bool = True
) -> bytes:
    """Build filters that ignore priority/source and PDU1 destination.

    A PDU2 DGN includes the PDU-specific byte in the group number.  For PDU1,
    that byte is a destination address and must be ignored.  The latter is
    required for destination-specific TM-102 proprietary status reports.
    """

    filters = []
    for dgn in sorted(set(dgns)):
        if not 0 <= dgn <= 0x3FFFF:
            raise ValueError("DGN must fit in 18 bits")
        pdu_format = (dgn >> 8) & 0xFF
        if pdu_format < 240:
            # Match EDP/DP/PF while accepting any PDU1 destination byte.
            dgn_mask = 0x3FF00
        else:
            dgn_mask = 0x3FFFF
        filters.append(
            _CAN_FILTER.pack(
                CAN_EFF_FLAG | ((dgn & dgn_mask) << 8),
                CAN_EFF_FLAG | (dgn_mask << 8),
            )
        )
    if include_j1939_request:
        # PDU1 request destination is the PS byte. Match only data-page + PF
        # so global and destination-specific requests are both delivered.
        filters.append(
            _CAN_FILTER.pack(
                CAN_EFF_FLAG | 0x00EA0000,
                CAN_EFF_FLAG | 0x01FF0000,
            )
        )
    if not filters:
        raise ValueError("at least one SocketCAN filter is required")
    return b"".join(filters)


def encode_socketcan_packet(frame: CanFrame) -> bytes:
    payload = frame.data.ljust(8, b"\x00")
    return _CAN_FRAME.pack(
        frame.can_id | CAN_EFF_FLAG,
        len(frame.data),
        payload,
    )


def decode_socketcan_packet(
    packet: bytes,
    *,
    timestamp: float,
    interface: str,
) -> CanFrame:
    if len(packet) != _CAN_FRAME.size:
        raise ValueError("Linux can_frame must be exactly 16 bytes")
    raw_id, dlc, payload = _CAN_FRAME.unpack(packet)
    if raw_id & CAN_ERR_FLAG:
        raise ValueError("SocketCAN error frame is not an RV-C data frame")
    if raw_id & CAN_RTR_FLAG:
        raise ValueError("remote-transmission frames are unsupported")
    if not raw_id & CAN_EFF_FLAG:
        raise ValueError("RV-C requires a 29-bit extended identifier")
    if dlc > 8:
        raise ValueError("invalid classic CAN data length")
    return CanFrame(
        timestamp=timestamp,
        interface=interface,
        can_id=raw_id & CAN_EFF_MASK,
        data=payload[:dlc],
    )


class SocketCanTransport:
    def __init__(
        self,
        interface: str,
        *,
        read_only: bool = True,
        clock=time.monotonic,
        dgns: Optional[Iterable[int]] = None,
    ) -> None:
        self.interface = interface
        self.read_only = read_only
        self.clock = clock
        self.dgns = None if dgns is None else tuple(dgns)
        self._socket: Optional[socket.socket] = None

    def open(self) -> None:
        if self._socket is not None:
            return
        if not hasattr(socket, "AF_CAN"):
            raise RuntimeError("SocketCAN is available only on Linux")
        can_socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            if self.dgns is not None:
                can_socket.setsockopt(
                    socket.SOL_CAN_RAW,
                    CAN_RAW_FILTER,
                    build_socketcan_filters(self.dgns),
                )
            can_socket.bind((self.interface,))
        except Exception:
            can_socket.close()
            raise
        self._socket = can_socket

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def fileno(self) -> int:
        if self._socket is None:
            raise RuntimeError("SocketCAN transport is not open")
        return self._socket.fileno()

    def recv(self, timeout: Optional[float] = None) -> CanFrame:
        if self._socket is None:
            raise RuntimeError("SocketCAN transport is not open")
        self._socket.settimeout(timeout)
        packet = self._socket.recv(_CAN_FRAME.size)
        return decode_socketcan_packet(
            packet,
            timestamp=self.clock(),
            interface=self.interface,
        )

    def send(self, frame: CanFrame) -> None:
        if self.read_only:
            raise PermissionError("SocketCAN transport is permanently read-only")
        if self._socket is None:
            raise RuntimeError("SocketCAN transport is not open")
        if frame.interface != self.interface:
            raise ValueError("refusing to transmit on a different CAN interface")
        written = self._socket.send(encode_socketcan_packet(frame))
        if written != _CAN_FRAME.size:
            raise OSError("short SocketCAN write")

    def __enter__(self) -> "SocketCanTransport":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
