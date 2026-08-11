"""Narrow Victron AC-input observation and guarded input-mode writes."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Optional


GRID_SOURCE = 1
GENERATOR_SOURCE = 2
SOURCE_LABEL_PATH = "/Settings/SystemSetup/AcInput1"
CURRENT_LIMIT_PATH = "/Ac/ActiveIn/CurrentLimit"
SOURCE_NAMES = {
    0: "unavailable",
    1: "grid",
    2: "genset",
    3: "shore",
    240: "inverting",
}


def _number(value) -> Optional[float]:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


@dataclass(frozen=True)
class VictronAcState:
    fresh: bool
    accepting_ac: bool
    l1_voltage: Optional[float]
    l2_voltage: Optional[float]
    l1_current: Optional[float]
    l2_current: Optional[float]
    input_current_limit: Optional[float]
    reported_source_raw: Optional[int]
    error: Optional[str] = None

    @property
    def active_input_voltage(self) -> Optional[float]:
        voltages = [
            value
            for value in (self.l1_voltage, self.l2_voltage)
            if value is not None
        ]
        return max(voltages) if voltages else None

    @property
    def active_input_l1_current(self) -> Optional[float]:
        return self.l1_current

    @property
    def active_input_l2_current(self) -> Optional[float]:
        return self.l2_current

    @property
    def active_input_total_current(self) -> Optional[float]:
        if self.l1_current is None or self.l2_current is None:
            return None
        return abs(self.l1_current) + abs(self.l2_current)

    @property
    def reported_source(self) -> str:
        return SOURCE_NAMES.get(self.reported_source_raw, "unknown")

    def both_legs_valid(
        self,
        *,
        minimum_voltage: float = 105.0,
        maximum_voltage: float = 132.0,
    ) -> bool:
        return bool(
            self.fresh
            and self.accepting_ac
            and self.l1_voltage is not None
            and self.l2_voltage is not None
            and minimum_voltage <= self.l1_voltage <= maximum_voltage
            and minimum_voltage <= self.l2_voltage <= maximum_voltage
        )


class VictronAcObserver:
    """Poll the active input using system state and direct VE.Bus values."""

    SERVICE = "com.victronenergy.system"

    def __init__(self, getter: Callable[[str, str], object]) -> None:
        self.getter = getter

    def read(self) -> VictronAcState:
        try:
            source = _number(
                self.getter(self.SERVICE, "/Ac/ActiveIn/Source")
            )
            connected = _number(
                self.getter(self.SERVICE, "/Ac/In/0/Connected")
            )
            vebus_service = self.getter(self.SERVICE, "/VebusService")
            if not isinstance(vebus_service, str) or not vebus_service:
                raise RuntimeError("VE.Bus service is unavailable")
            l1_voltage = _number(
                self.getter(vebus_service, "/Ac/ActiveIn/L1/V")
            )
            l2_voltage = _number(
                self.getter(vebus_service, "/Ac/ActiveIn/L2/V")
            )
            l1_current = _number(
                self.getter(vebus_service, "/Ac/ActiveIn/L1/I")
            )
            l2_current = _number(
                self.getter(vebus_service, "/Ac/ActiveIn/L2/I")
            )
            input_current_limit = _number(
                self.getter(
                    vebus_service,
                    "/Ac/ActiveIn/CurrentLimit",
                )
            )
        except Exception as error:
            return VictronAcState(
                fresh=False,
                accepting_ac=False,
                l1_voltage=None,
                l2_voltage=None,
                l1_current=None,
                l2_current=None,
                input_current_limit=None,
                reported_source_raw=None,
                error=str(error),
            )

        source_number = None if source is None else int(source)
        return VictronAcState(
            fresh=source_number is not None and connected is not None,
            accepting_ac=bool(
                connected == 1 and source_number not in {None, 0, 240}
            ),
            l1_voltage=l1_voltage,
            l2_voltage=l2_voltage,
            l1_current=l1_current,
            l2_current=l2_current,
            input_current_limit=input_current_limit,
            reported_source_raw=source_number,
        )


@dataclass(frozen=True)
class SourceLabelDecision:
    target: int
    reason: str
    allow_50_amp_current_limit: bool = False


class GeneratorSourceLabelHeuristic:
    """Latch Generator after a guarded delay; fail back to Grid.

    This is explicitly a temporary heuristic, not proof of the physical ATS
    position.  Once Generator is selected it stays selected until the TM-102
    reports a stop or its status becomes stale.
    """

    RUNNING_STATES = frozenset({3, 6, 7, 8, 9})

    def __init__(
        self,
        *,
        delay_seconds: float = 60.0,
        stable_seconds: float = 5.0,
        status_stale_seconds: float = 90.0,
    ) -> None:
        self.delay_seconds = float(delay_seconds)
        self.stable_seconds = float(stable_seconds)
        self.status_stale_seconds = float(status_stale_seconds)
        self._running_since: Optional[float] = None
        self._stable_since: Optional[float] = None
        self._saw_ac_loss = False
        self._generator_latched = False
        self._fifty_confirmed = False
        self._fifty_revoked = False

    def _reset(self) -> None:
        self._running_since = None
        self._stable_since = None
        self._saw_ac_loss = False
        self._generator_latched = False
        self._fifty_confirmed = False
        self._fifty_revoked = False

    def update(
        self,
        *,
        now: float,
        generator_status_raw: Optional[int],
        generator_status_seen: Optional[float],
        ac_state: VictronAcState,
    ) -> SourceLabelDecision:
        status_fresh = bool(
            generator_status_seen is not None
            and now >= generator_status_seen
            and now - generator_status_seen <= self.status_stale_seconds
        )
        running = bool(
            status_fresh and generator_status_raw in self.RUNNING_STATES
        )

        if not running:
            reason = (
                "generator status stale; fail-safe Grid"
                if generator_status_raw in self.RUNNING_STATES
                else "generator not running"
            )
            self._reset()
            return SourceLabelDecision(GRID_SOURCE, reason)

        if self._running_since is None:
            self._running_since = now

        ac_valid = ac_state.both_legs_valid()
        if ac_valid:
            if self._stable_since is None:
                self._stable_since = now
        else:
            self._stable_since = None
            self._saw_ac_loss = True

        stable_for = (
            0.0
            if self._stable_since is None
            else now - self._stable_since
        )
        running_for = now - self._running_since
        full_confirmation = bool(
            ac_valid
            and stable_for >= self.stable_seconds
            and running_for >= self.delay_seconds
        )

        if not ac_valid and self._fifty_confirmed:
            self._fifty_revoked = True

        if self._generator_latched:
            if full_confirmation and not self._fifty_revoked:
                self._fifty_confirmed = True
            allow_50 = bool(self._fifty_confirmed and not self._fifty_revoked)
            return SourceLabelDecision(
                GENERATOR_SOURCE,
                (
                    "Generator latched; 50 A confirmation complete"
                    if allow_50
                    else "Generator latched; retaining shore current limit"
                ),
                allow_50,
            )

        if ac_valid and stable_for >= self.stable_seconds:
            if self._saw_ac_loss and running_for < self.delay_seconds:
                self._generator_latched = True
                return SourceLabelDecision(
                    GENERATOR_SOURCE,
                    "post-start AC loss and stable two-leg return",
                    False,
                )
            if full_confirmation:
                self._generator_latched = True
                self._fifty_confirmed = True
                return SourceLabelDecision(
                    GENERATOR_SOURCE,
                    "60-second running fallback with both AC legs stable",
                    True,
                )

        return SourceLabelDecision(
            GRID_SOURCE,
            "waiting for guarded generator-label confirmation",
        )


class VictronSourceLabelWriter:
    """Idempotently write only the configured type of physical AC input 1."""

    SERVICE = "com.victronenergy.settings"

    def __init__(
        self,
        getter: Callable[[str, str], object],
        setter: Callable[[str, str, int], object],
    ) -> None:
        self.getter = getter
        self.setter = setter

    def ensure(self, target: int) -> bool:
        if target not in {GRID_SOURCE, GENERATOR_SOURCE}:
            raise ValueError("source label must be Grid or Generator")
        current = _number(self.getter(self.SERVICE, SOURCE_LABEL_PATH))
        if current is not None and int(current) == target:
            return False
        result = self.setter(self.SERVICE, SOURCE_LABEL_PATH, target)
        if result not in (None, 0):
            raise RuntimeError("Victron source-label write failed: {}".format(result))
        return True

    def current(self) -> int:
        current = _number(self.getter(self.SERVICE, SOURCE_LABEL_PATH))
        if current is None:
            raise RuntimeError("Victron source label is unavailable")
        return int(current)


class VictronCurrentLimitWriter:
    """Write only the remotely-overridable active VE.Bus input limit."""

    SYSTEM_SERVICE = "com.victronenergy.system"

    def __init__(
        self,
        getter: Callable[[str, str], object],
        setter: Callable[[str, str, float], object],
        *,
        clock: Callable[[], float] = time.monotonic,
        verify_timeout_seconds: float = 5.0,
    ) -> None:
        self.getter = getter
        self.setter = setter
        self.clock = clock
        self.verify_timeout_seconds = float(verify_timeout_seconds)
        self._pending_target: Optional[float] = None
        self._pending_since: Optional[float] = None

    def _vebus_service(self) -> str:
        service = self.getter(self.SYSTEM_SERVICE, "/VebusService")
        if not isinstance(service, str) or not service:
            raise RuntimeError("VE.Bus service is unavailable")
        return service

    def current(self) -> float:
        current = _number(
            self.getter(self._vebus_service(), CURRENT_LIMIT_PATH)
        )
        if current is None:
            raise RuntimeError("VE.Bus input current limit is unavailable")
        return current

    def ensure(self, target: float) -> bool:
        if (
            isinstance(target, bool)
            or not isinstance(target, (int, float))
            or not math.isfinite(float(target))
            or not 0 <= float(target) <= 50
        ):
            raise ValueError("input current limit must be between 0 and 50 amps")
        target_number = float(target)
        service = self._vebus_service()
        current = _number(self.getter(service, CURRENT_LIMIT_PATH))
        at_target = bool(
            current is not None and abs(current - target_number) <= 0.05
        )
        now = self.clock()

        if self._pending_target is not None:
            if abs(self._pending_target - target_number) > 0.05:
                # A fail-safe target must supersede an earlier asynchronous
                # request even when the old live value already equals it.
                pass
            elif at_target:
                self._pending_target = None
                self._pending_since = None
                return False
            elif (
                self._pending_since is not None
                and now - self._pending_since <= self.verify_timeout_seconds
            ):
                return False
            else:
                pending = self._pending_target
                self._pending_target = None
                self._pending_since = None
                raise RuntimeError(
                    "Victron current limit did not verify at {} A within "
                    "{:.1f} seconds".format(
                        pending,
                        self.verify_timeout_seconds,
                    )
                )
        elif at_target:
            return False

        result = self.setter(service, CURRENT_LIMIT_PATH, target_number)
        if result not in (None, 0):
            raise RuntimeError(
                "Victron current-limit write failed: {}".format(result)
            )
        self._pending_target = target_number
        self._pending_since = now
        return True


class VictronInputModeController:
    """Apply ordered source/current transitions with a shore-first fail-safe."""

    def __init__(
        self,
        source_writer: VictronSourceLabelWriter,
        current_writer: Optional[VictronCurrentLimitWriter],
        *,
        generator_current_limit_amps: float = 50.0,
        shore_current_limit_fallback_amps: float = 30.0,
    ) -> None:
        self.source_writer = source_writer
        self.current_writer = current_writer
        self.generator_current_limit_amps = float(
            generator_current_limit_amps
        )
        self.shore_current_limit_fallback_amps = float(
            shore_current_limit_fallback_amps
        )
        self.restore_current_limit: Optional[float] = None

    def startup_safe(self) -> list[str]:
        """Recover a prior Generator state without overriding normal shore limits."""

        actions = []
        if (
            self.current_writer is not None
            and self.source_writer.current() == GENERATOR_SOURCE
            and self.current_writer.ensure(
                self.shore_current_limit_fallback_amps
            )
        ):
            actions.append(
                "input current limit restored to {:.1f} A".format(
                    self.shore_current_limit_fallback_amps
                )
            )
        if self.source_writer.ensure(GRID_SOURCE):
            actions.append("source label restored to Grid")
        self.restore_current_limit = None
        return actions

    def _capture_shore_limit(self, ac_state: VictronAcState) -> None:
        if self.current_writer is None or self.restore_current_limit is not None:
            return
        observed = ac_state.input_current_limit
        self.restore_current_limit = (
            observed
            if observed is not None and 0 <= observed <= 30.1
            else self.shore_current_limit_fallback_amps
        )

    def apply(
        self,
        decision: SourceLabelDecision,
        ac_state: VictronAcState,
    ) -> list[str]:
        if decision.target != GENERATOR_SOURCE:
            return self.restore_grid()

        actions = []
        self._capture_shore_limit(ac_state)
        # Generator ordering is label first, then the higher current limit.
        if self.source_writer.ensure(GENERATOR_SOURCE):
            actions.append("source label changed to Generator")

        if self.current_writer is not None:
            target = (
                self.generator_current_limit_amps
                if decision.allow_50_amp_current_limit
                else self.restore_current_limit
            )
            if target is not None and self.current_writer.ensure(target):
                if decision.allow_50_amp_current_limit:
                    actions.append(
                        "input current limit changed to {:.1f} A".format(target)
                    )
                else:
                    actions.append(
                        "input current limit reduced to {:.1f} A".format(target)
                    )
        return actions

    def restore_grid(self) -> list[str]:
        actions = []
        target = self.restore_current_limit
        if (
            target is None
            and self.current_writer is not None
            and self.source_writer.current() == GENERATOR_SOURCE
        ):
            target = self.shore_current_limit_fallback_amps

        # Shore ordering is lower current limit first, then relabel Grid.
        if (
            self.current_writer is not None
            and target is not None
            and self.current_writer.ensure(target)
        ):
            actions.append(
                "input current limit restored to {:.1f} A".format(target)
            )
        if self.source_writer.ensure(GRID_SOURCE):
            actions.append("source label restored to Grid")
        self.restore_current_limit = None
        return actions


def dbus_getter(bus):
    def get(service: str, path: str):
        obj = bus.get_object(service, path)
        return obj.GetValue(dbus_interface="com.victronenergy.BusItem")

    return get


def dbus_int_setter(bus):
    import dbus  # type: ignore

    def set_value(service: str, path: str, value: int):
        obj = bus.get_object(service, path)
        return obj.SetValue(
            dbus.Int32(value),
            dbus_interface="com.victronenergy.BusItem",
        )

    return set_value


def dbus_float_setter(bus):
    import dbus  # type: ignore

    def set_value(service: str, path: str, value: float):
        obj = bus.get_object(service, path)
        return obj.SetValue(
            dbus.Double(value),
            dbus_interface="com.victronenergy.BusItem",
        )

    return set_value
