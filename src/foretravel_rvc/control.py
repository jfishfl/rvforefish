"""Pure, replay-testable control state machines.

The engine owns no threads, sockets, or D-Bus objects.  A runtime adapter feeds
decoded messages and injects a sender.  This separation is intentional: every
transmission decision can be tested without access to a live coach network.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Callable, Dict, Optional, Tuple

from .can import CanFrame
from .commands import (
    autofill_command,
    generator_demand_command,
    water_pump_command,
)
from .config import RuntimeConfig
from .decode import (
    DGN_GENERATOR_DEMAND_COMMAND,
    DecodedMessage,
    MessageKind,
)
from .model import StateReducer


class CommandRejected(RuntimeError):
    """A user-visible command failed a safety or authorization gate."""


class ControlPhase(str, Enum):
    IDLE = "idle"
    AWAITING_ACK = "awaiting_ack"
    RECOVERING = "recovering"
    STARTING = "starting"
    RUNNING = "running"
    UNLOAD_REQUIRED = "unload_required"
    COOLDOWN = "cooldown"
    EXTERNAL_DEMAND = "external_demand"
    FAULT = "fault"


@dataclass
class PendingCommand:
    name: str
    desired: bool
    frame: CanFrame
    attempts: int
    retry_at: float


@dataclass
class ControlView:
    requested: Optional[bool] = None
    actual: Optional[bool] = None
    phase: ControlPhase = ControlPhase.IDLE
    fault: Optional[str] = None


class ControlEngine:
    def __init__(
        self,
        config: RuntimeConfig,
        sender: Callable[[CanFrame], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        generator_demand_hook: Optional[Callable[[bool], None]] = None,
        autofill_active_hook: Optional[Callable[[bool], None]] = None,
    ) -> None:
        config.validate()
        self.config = config
        self.sender = sender
        self.clock = clock
        self.generator_demand_hook = generator_demand_hook or (lambda active: None)
        self.autofill_active_hook = autofill_active_hook or (
            lambda active: None
        )
        self.reducer = StateReducer(tm102_source=config.tm102_source)
        self.views: Dict[str, ControlView] = {
            "water_pump": ControlView(),
            "autofill": ControlView(),
            "generator": ControlView(),
        }
        self.pending: Dict[str, PendingCommand] = {}
        self.own_autofill_request = False
        self.autofill_cleanup_required = False
        self.autofill_max_run_deadline: Optional[float] = None
        self.own_generator_demand = False
        self.generator_cleanup_required = False
        self.generator_release_attempts = 0
        self.generator_release_retry_at: Optional[float] = None
        self.generator_keepalive_at: Optional[float] = None
        self.generator_start_deadline: Optional[float] = None
        self.generator_cooldown_deadline: Optional[float] = None
        self.generator_max_run_deadline: Optional[float] = None
        self.generator_stop_escalation_deadline: Optional[float] = None
        self.generator_stop_escalated = False
        self.generator_stop_requested = False
        self.generator_recovery_pending = False
        self.generator_shutdown_requested = False
        self.generator_unloaded_since: Optional[float] = None
        self.generator_source_confirmed = False
        self.generator_input_l1_current: Optional[float] = None
        self.generator_input_l2_current: Optional[float] = None
        self.generator_input_total_current: Optional[float] = None
        self.generator_input_observed_at: Optional[float] = None

    def _now(self, value: Optional[float]) -> float:
        return self.clock() if value is None else value

    def _source(self) -> int:
        if self.config.source_address is None:
            raise CommandRejected("bridge source address has not been validated")
        return self.config.source_address

    def _require_feature(self, name: str) -> None:
        if not self.config.feature_can_transmit(name):
            raise CommandRejected("{} transmission is not armed".format(name))

    def _fresh(self, kind: MessageKind, now: float) -> bool:
        timestamp = self.reducer.snapshot.last_seen.get(kind)
        return (
            timestamp is not None
            and now - timestamp <= self.config.status_max_age_seconds
        )

    def _require_fresh(self, kind: MessageKind, now: float) -> None:
        if not self._fresh(kind, now):
            raise CommandRejected(
                "{} status is missing or stale".format(kind.value)
            )

    def _fresh_tank(self, instance: int, now: float) -> bool:
        timestamp = self.reducer.snapshot.tank_seen.get(instance)
        return (
            timestamp is not None
            and now - timestamp <= self.config.status_max_age_seconds
        )

    def observe_generator_input(
        self,
        *,
        generator_source_confirmed: bool,
        l1_current: Optional[float],
        l2_current: Optional[float],
        now: Optional[float] = None,
    ) -> None:
        """Record read-only VE.Bus input load for cooldown verification.

        Both split-phase legs are mandatory.  The values are never used to
        identify the source; that decision must already have authoritative ATS,
        generator-AC, and VE.Bus agreement.
        """

        current = self._now(now)
        self.generator_source_confirmed = bool(generator_source_confirmed)

        def valid_current(value: Optional[float]) -> Optional[float]:
            if value is None or isinstance(value, bool):
                return None
            number = float(value)
            return abs(number) if math.isfinite(number) else None

        self.generator_input_l1_current = valid_current(l1_current)
        self.generator_input_l2_current = valid_current(l2_current)
        self.generator_input_total_current = (
            self.generator_input_l1_current + self.generator_input_l2_current
            if self.generator_input_l1_current is not None
            and self.generator_input_l2_current is not None
            else None
        )
        self.generator_input_observed_at = current

    def generator_load_fresh(self, now: float) -> bool:
        return (
            self.generator_input_observed_at is not None
            and now - self.generator_input_observed_at
            <= self.config.status_max_age_seconds
        )

    def generator_unload_interlock(self, now: float) -> Tuple[bool, str]:
        threshold = self.config.generator_unloaded_current_threshold_amps
        if not self.generator_source_confirmed:
            return False, "authoritative generator source is not confirmed"
        if not self.generator_load_fresh(now):
            return False, "VE.Bus input-current observation is missing or stale"
        if self.generator_input_total_current is None:
            return False, "both VE.Bus input-leg currents are required"
        if threshold is None:
            return False, "unloaded-current threshold is not configured"
        if self.generator_input_total_current > threshold:
            return (
                False,
                "generator load {:.1f} A exceeds unloaded threshold {:.1f} A".format(
                    self.generator_input_total_current, threshold
                ),
            )
        return True, "both legs are below the unloaded-current threshold"

    def autofill_start_interlock(
        self, *, now: Optional[float] = None
    ) -> Tuple[bool, str]:
        """Return whether a remote AutoFill start is presently safe.

        The TM-102 remains the primary fill controller.  This bridge adds a
        fail-closed admission check based only on fresh status plus the
        documented TM-102 configuration report observed since process start.
        """

        current = self._now(now)
        snapshot = self.reducer.snapshot
        if not self.config.autofill_interlocks_verified:
            return False, "installation interlocks have not been verified"
        if not self._fresh(MessageKind.AUTOFILL_STATUS, current):
            return False, "autofill status is missing or stale"
        if not self._fresh(MessageKind.WATER_PUMP_STATUS, current):
            return False, "water pump status is missing or stale"
        if not self._fresh_tank(0, current):
            return False, "fresh tank status is missing or stale"
        if not snapshot.autofill_configuration:
            return False, "TM-102 autofill configuration has not been observed"

        configuration = snapshot.autofill_configuration
        cutoff = configuration.get("cutoff_level_percent")
        timeout = configuration.get("timeout_minutes")
        check_pressure = configuration.get("check_water_pressure")
        pump_cancels = configuration.get("pump_on_cancels_fill")
        bypass_disables = configuration.get("pump_bypass_disables_fill")
        if cutoff is None or not 0 < float(cutoff) <= 100:
            return False, "TM-102 autofill cutoff is unavailable or invalid"
        if timeout is None or float(timeout) <= 0:
            return False, "TM-102 no-level-change timeout is disabled or invalid"
        if any(
            value is None
            for value in (check_pressure, pump_cancels, bypass_disables)
        ):
            return False, "TM-102 autofill policy flags are unavailable"

        fresh_tank = snapshot.tank_statuses.get(0, {})
        level = fresh_tank.get("relative_level_percent")
        if level is None:
            return False, "fresh tank level is unavailable or invalid"
        if float(level) >= float(cutoff):
            return False, "fresh tank is already at or above the cutoff level"
        if snapshot.pump_on is None:
            return False, "water pump operating state is unavailable"
        if snapshot.pump_on and (pump_cancels or bypass_disables):
            return False, "water pump state conflicts with TM-102 fill policy"
        if check_pressure and snapshot.water_hookup_detected is not True:
            return False, "TM-102 requires a recently detected water hookup"
        return True, "ready"

    def _send(self, frame: CanFrame) -> None:
        if not self.config.transmission_armed:
            raise CommandRejected("runtime is monitor-only")
        self.sender(frame)

    def _begin_acknowledged_command(
        self,
        *,
        name: str,
        desired: bool,
        frame: CanFrame,
        now: float,
    ) -> None:
        self._send(frame)
        self.pending[name] = PendingCommand(
            name=name,
            desired=desired,
            frame=frame,
            attempts=1,
            retry_at=now + self.config.ack_timeout_seconds,
        )
        view = self.views[name]
        view.requested = desired
        view.phase = ControlPhase.AWAITING_ACK
        view.fault = None

    def request_water_pump(self, on: bool, *, now: Optional[float] = None) -> None:
        current = self._now(now)
        self._require_feature("water_pump")
        self._require_fresh(MessageKind.WATER_PUMP_STATUS, current)
        if self.reducer.snapshot.pump_on is on:
            self.views["water_pump"] = ControlView(
                requested=on, actual=on, phase=ControlPhase.IDLE
            )
            return
        self._begin_acknowledged_command(
            name="water_pump",
            desired=on,
            frame=water_pump_command(self._source(), on),
            now=current,
        )

    def request_autofill(self, on: bool, *, now: Optional[float] = None) -> None:
        current = self._now(now)
        gate = "autofill_start" if on else "autofill_stop"
        self._require_feature(gate)
        status_fresh = self._fresh(MessageKind.AUTOFILL_STATUS, current)
        if on:
            ready, reason = self.autofill_start_interlock(now=current)
            if not ready:
                raise CommandRejected(reason)
        pending = self.pending.get("autofill")
        if (
            status_fresh
            and self.reducer.snapshot.autofill_operating is on
            and (pending is None or pending.desired is on)
        ):
            self.views["autofill"] = ControlView(
                requested=on, actual=on, phase=ControlPhase.IDLE
            )
            if not on:
                self.own_autofill_request = False
                self.autofill_cleanup_required = False
                self.autofill_active_hook(False)
                self.autofill_max_run_deadline = None
            return
        if on:
            self.own_autofill_request = True
            self.autofill_cleanup_required = True
            # Persist cleanup intent before the first Start frame.  A crash
            # between marker creation and CAN TX is harmless; the inverse
            # ordering could orphan an active fill with no recovery marker.
            self.autofill_active_hook(True)
        try:
            self._begin_acknowledged_command(
                name="autofill",
                desired=on,
                frame=autofill_command(self._source(), on),
                now=current,
            )
        except Exception:
            if on:
                self.own_autofill_request = False
            raise
        if not on:
            self.own_autofill_request = False
        self.autofill_max_run_deadline = (
            current + self.config.autofill_max_run_seconds
            if on and self.config.autofill_max_run_seconds is not None
            else None
        )

    def _generator_running(self) -> bool:
        return self.reducer.snapshot.generator_status_raw in {3, 6, 7, 8, 9}

    def _begin_generator_stop(self, reason: str, *, now: float) -> None:
        timeout = self.config.generator_stop_escalation_seconds
        if timeout is None:
            raise CommandRejected("generator stop escalation timer is not configured")
        if self.generator_stop_requested:
            return
        self.generator_stop_requested = True
        self.generator_start_deadline = None
        self.generator_max_run_deadline = None
        self.generator_unloaded_since = None
        self.generator_cooldown_deadline = None
        self.generator_stop_escalation_deadline = now + timeout
        self.generator_stop_escalated = False
        view = self.views["generator"]
        view.requested = False
        view.phase = ControlPhase.UNLOAD_REQUIRED
        view.fault = reason

    def request_generator(self, on: bool, *, now: Optional[float] = None) -> None:
        current = self._now(now)
        self._require_feature("generator_demand")
        view = self.views["generator"]

        if on:
            self._require_fresh(MessageKind.GENERATOR_DEMAND_STATUS, current)
            self._require_fresh(MessageKind.GENERATOR_STATUS_1, current)
            if self.reducer.snapshot.generator_locked is not False:
                raise CommandRejected("TM-102 generator lock is active or unknown")
            if self.reducer.snapshot.generator_status_raw == 5:
                raise CommandRejected("generator reports a fault")
            if self.own_generator_demand:
                return
            if self.generator_cleanup_required:
                raise CommandRejected(
                    "prior generator demand release is not yet confirmed"
                )
            # As with AutoFill, persist cleanup intent before transmitting the
            # first demand.  If TX fails or the process dies, startup recovery
            # still has enough state to send a source-specific Release.
            self.generator_cleanup_required = True
            self.generator_demand_hook(True)
            self.own_generator_demand = True
            try:
                self._send(generator_demand_command(self._source(), True))
            except Exception:
                self.own_generator_demand = False
                raise
            self.generator_keepalive_at = (
                current + self.config.generator_keepalive_seconds
            )
            self.generator_start_deadline = (
                current + self.config.generator_start_timeout_seconds
            )
            self.generator_cooldown_deadline = None
            self.generator_max_run_deadline = None
            self.generator_stop_escalation_deadline = None
            self.generator_stop_escalated = False
            self.generator_stop_requested = False
            self.generator_recovery_pending = False
            self.generator_unloaded_since = None
            view.requested = True
            view.phase = ControlPhase.STARTING
            view.fault = None
            return

        view.requested = False
        if not self.own_generator_demand:
            view.phase = (
                ControlPhase.EXTERNAL_DEMAND
                if self.reducer.snapshot.generator_demand
                else ControlPhase.IDLE
            )
            return
        if (
            self._fresh(MessageKind.GENERATOR_STATUS_1, current)
            and not self._generator_running()
        ):
            self._release_generator("user release; generator is stopped", now=current)
            return
        # Stop admission deliberately does not require fresh RV-C demand or
        # engine status.  Rejecting an Off request because telemetry is stale
        # could leave this source's demand asserted indefinitely.  Unless a
        # fresh engine status proves the generator is already stopped, retain
        # demand while the independent source/load observer proves a safe
        # unload and cooldown.
        self._begin_generator_stop("turn off AC loads to begin cooldown", now=current)

    def _send_generator_release(self, now: float) -> None:
        self._send(generator_demand_command(self._source(), False))
        self.generator_release_attempts += 1
        self.generator_release_retry_at = (
            now + self.config.ack_timeout_seconds
        )

    def _release_generator(self, reason: str, *, now: float) -> None:
        if self.own_generator_demand or self.generator_cleanup_required:
            if not self.generator_cleanup_required:
                self.generator_cleanup_required = True
                self.generator_demand_hook(True)
            self._send_generator_release(now)
        self.own_generator_demand = False
        self.generator_keepalive_at = None
        self.generator_start_deadline = None
        self.generator_cooldown_deadline = None
        self.generator_max_run_deadline = None
        self.generator_stop_escalation_deadline = None
        self.generator_stop_escalated = False
        self.generator_stop_requested = False
        self.generator_recovery_pending = False
        self.generator_unloaded_since = None
        view = self.views["generator"]
        view.requested = False
        view.phase = (
            ControlPhase.EXTERNAL_DEMAND
            if self.reducer.snapshot.generator_demand
            else ControlPhase.IDLE
        )
        if reason:
            view.fault = None

    def observe(
        self, message: DecodedMessage, *, now: Optional[float] = None
    ) -> None:
        current = self._now(now)
        self.reducer.apply(message)

        if message.kind == MessageKind.REQUEST:
            self._handle_request(message, current)
            return

        if message.frame.source != self.config.tm102_source:
            return

        if message.kind == MessageKind.WATER_PUMP_STATUS:
            actual = message.fields["on"]
            self.views["water_pump"].actual = actual
            self._ack_if_matching("water_pump", actual)
        elif message.kind == MessageKind.AUTOFILL_STATUS:
            actual = message.fields["operating"]
            self.views["autofill"].actual = actual
            self._ack_if_matching("autofill", actual)
            if actual is False:
                cleanup_was_required = self.autofill_cleanup_required
                self.own_autofill_request = False
                self.autofill_cleanup_required = False
                if cleanup_was_required:
                    self.autofill_active_hook(False)
                self.autofill_max_run_deadline = None
        elif message.kind == MessageKind.GENERATOR_STATUS_1:
            status = message.fields["status_raw"]
            generator_view = self.views["generator"]
            generator_view.actual = self._generator_running()
            if self.generator_recovery_pending:
                self._evaluate_generator_recovery(current)
                return
            if status == 3 and self.own_generator_demand:
                self.generator_start_deadline = None
                if self.generator_stop_requested:
                    generator_view.phase = ControlPhase.UNLOAD_REQUIRED
                else:
                    generator_view.phase = ControlPhase.RUNNING
                if (
                    not self.generator_stop_requested
                    and self.config.generator_max_run_seconds is not None
                ):
                    self.generator_max_run_deadline = (
                        current + self.config.generator_max_run_seconds
                    )
            elif status == 5:
                if self.own_generator_demand:
                    self._release_generator("generator fault", now=current)
                generator_view.phase = ControlPhase.FAULT
                generator_view.fault = "generator fault"
            elif status == 0:
                if self.own_generator_demand:
                    if (
                        generator_view.phase == ControlPhase.STARTING
                        and self.generator_start_deadline is not None
                        and current < self.generator_start_deadline
                    ):
                        # TM-102 continues broadcasting Stopped during the
                        # normal demand -> preheat/crank transition. A repeat
                        # of the pre-start state is not evidence that the
                        # start was aborted. Keep demand asserted until an
                        # actual Running/Fault report or the bounded start
                        # timeout resolves the attempt.
                        pass
                    else:
                        self._release_generator(
                            "generator stopped outside bridge control",
                            now=current,
                        )
                        generator_view.phase = ControlPhase.FAULT
                        generator_view.fault = (
                            "generator stopped while bridge demand was active; "
                            "bridge demand released"
                        )
                else:
                    generator_view.phase = (
                        ControlPhase.EXTERNAL_DEMAND
                        if self.reducer.snapshot.generator_demand
                        else ControlPhase.IDLE
                    )
        elif message.kind == MessageKind.GENERATOR_DEMAND_STATUS:
            if self.generator_recovery_pending:
                self._evaluate_generator_recovery(current)
                return
            # This bridge is a network-demand source, so Network Demand False
            # is the authoritative category-level proof that our assertion is
            # gone.  Overall Demand can be False while Network Demand remains
            # True (observed live across a Cerbo reboot), and it can remain
            # True for an unrelated internal/manual demand after our network
            # assertion has cleared.
            if (
                self.generator_cleanup_required
                and not self.own_generator_demand
                and message.fields["network_demand"] is False
            ):
                self.generator_cleanup_required = False
                self.generator_release_attempts = 0
                self.generator_release_retry_at = None
                self.generator_demand_hook(False)

    def _evaluate_generator_recovery(self, current: float) -> None:
        """Resolve a persistent ownership marker without creating a new start.

        Recovery deliberately transmits nothing until fresh TM-102 demand and
        engine status are both available.  Network Demand False proves this
        network source's stale marker can be cleared, even if an unrelated
        internal/manual demand keeps Overall Demand True.  If Network Demand
        remains asserted while the engine is active, the bridge conservatively
        resumes ownership and enters the normal unload/cooldown state machine
        without sending a new Start frame.  A source-specific Release is safe
        only after fresh status proves the engine is stopped or faulted.
        """

        if not self.generator_recovery_pending:
            return
        if not self._fresh(MessageKind.GENERATOR_DEMAND_STATUS, current):
            return
        if not self._fresh(MessageKind.GENERATOR_STATUS_1, current):
            return

        network_demand = self.reducer.snapshot.generator_network_demand
        status = self.reducer.snapshot.generator_status_raw
        view = self.views["generator"]
        if network_demand is False:
            self.generator_recovery_pending = False
            self.generator_cleanup_required = False
            self.generator_release_attempts = 0
            self.generator_release_retry_at = None
            self.generator_demand_hook(False)
            view.requested = False
            view.phase = ControlPhase.IDLE
            view.fault = None
            return
        if network_demand is not True or status is None:
            return
        if status in {0, 5}:
            self.generator_recovery_pending = False
            self._send_generator_release(current)
            view.requested = False
            view.phase = ControlPhase.FAULT
            view.fault = (
                "stale demand marker released only after fresh status proved "
                "the generator stopped or faulted"
            )
            return

        self.generator_recovery_pending = False
        self.own_generator_demand = True
        # Live TM-102 evidence shows that a one-shot network demand expires at
        # its configured minimum-cycle boundary without first polling this
        # source.  Once fresh source-specific demand and active engine status
        # prove that this marker is ours, reassert the same cooperative demand
        # immediately and then keep it alive through the normal unload/cooldown
        # sequence.  This payload has no manual, quiet-time, or activity reset.
        self._send_generator_keepalive(current)
        self._begin_generator_stop(
            "recovered active demand; unload required before release",
            now=current,
        )

    def _send_generator_keepalive(self, now: float) -> None:
        self._send(generator_demand_command(self._source(), True))
        self.generator_keepalive_at = (
            now + self.config.generator_keepalive_seconds
        )

    def _tick_generator_keepalive(self, current: float) -> None:
        if not self.own_generator_demand:
            self.generator_keepalive_at = None
            return
        if self.generator_keepalive_at is None:
            self.generator_keepalive_at = (
                current + self.config.generator_keepalive_seconds
            )
            return
        if current >= self.generator_keepalive_at:
            self._send_generator_keepalive(current)

    def _handle_request(self, message: DecodedMessage, now: float) -> None:
        if not self.own_generator_demand:
            return
        if message.frame.source != self.config.tm102_source:
            return
        if message.fields["requested_pgn"] != DGN_GENERATOR_DEMAND_COMMAND:
            return
        if message.frame.destination not in {0xFF, self._source()}:
            return
        if not self._fresh(MessageKind.GENERATOR_DEMAND_STATUS, now):
            return
        self._send_generator_keepalive(now)

    def _ack_if_matching(self, name: str, actual: Optional[bool]) -> None:
        pending = self.pending.get(name)
        if pending is None or actual is None or actual != pending.desired:
            return
        del self.pending[name]
        view = self.views[name]
        view.phase = ControlPhase.IDLE
        view.fault = None

    def _tick_generator_stop(self, current: float) -> None:
        """Require a continuously unloaded interval before demand release."""

        view = self.views["generator"]
        if (
            not self.generator_stop_escalated
            and self.generator_stop_escalation_deadline is not None
            and current >= self.generator_stop_escalation_deadline
        ):
            # A timer is not evidence that a hot generator is safe to stop.
            # Escalate visibly, but retain our demand until the same measured
            # unload and full cooldown proof succeeds.
            self.generator_stop_escalated = True

        def stop_fault(reason: str) -> str:
            if not self.generator_stop_escalated:
                return reason
            return "STOP ESCALATED; demand retained: {}".format(reason)

        unloaded, reason = self.generator_unload_interlock(current)
        if not unloaded:
            self.generator_unloaded_since = None
            self.generator_cooldown_deadline = None
            view.phase = ControlPhase.UNLOAD_REQUIRED
            view.fault = stop_fault(reason)
            return

        if self.generator_unloaded_since is None:
            self.generator_unloaded_since = current
        confirmed_for = current - self.generator_unloaded_since
        if confirmed_for < self.config.generator_unloaded_confirm_seconds:
            self.generator_cooldown_deadline = None
            view.phase = ControlPhase.UNLOAD_REQUIRED
            view.fault = stop_fault(
                "confirming unloaded state for {:.0f} more seconds".format(
                    self.config.generator_unloaded_confirm_seconds
                    - confirmed_for
                )
            )
            return

        if self.generator_cooldown_deadline is None:
            self.generator_cooldown_deadline = (
                current + self.config.generator_cooldown_seconds
            )
        view.phase = ControlPhase.COOLDOWN
        view.fault = (
            "STOP ESCALATED; demand retained through full cooldown"
            if self.generator_stop_escalated
            else None
        )
        if current >= self.generator_cooldown_deadline:
            self._release_generator("unloaded cooldown complete", now=current)

    def tick(self, *, now: Optional[float] = None) -> None:
        current = self._now(now)

        for name, pending in list(self.pending.items()):
            if current < pending.retry_at:
                continue
            if pending.attempts <= self.config.max_retries:
                self._send(pending.frame)
                pending.attempts += 1
                pending.retry_at = current + self.config.ack_timeout_seconds
            else:
                del self.pending[name]
                view = self.views[name]
                view.phase = ControlPhase.FAULT
                view.fault = "no TM-102 status acknowledgment"

        if self.own_autofill_request:
            if (
                self.autofill_max_run_deadline is not None
                and current >= self.autofill_max_run_deadline
            ):
                self._begin_acknowledged_command(
                    name="autofill",
                    desired=False,
                    frame=autofill_command(self._source(), False),
                    now=current,
                )
                self.own_autofill_request = False
                self.autofill_max_run_deadline = None
                self.views["autofill"].fault = (
                    "maximum run time reached; stop requested"
                )
            elif (
                not self._fresh(MessageKind.AUTOFILL_STATUS, current)
                or not self._fresh(MessageKind.WATER_PUMP_STATUS, current)
                or not self._fresh_tank(0, current)
            ):
                self._begin_acknowledged_command(
                    name="autofill",
                    desired=False,
                    frame=autofill_command(self._source(), False),
                    now=current,
                )
                self.own_autofill_request = False
                self.autofill_max_run_deadline = None
                self.views["autofill"].fault = (
                    "required status became stale; stop requested"
                )

        if self.generator_recovery_pending:
            self._evaluate_generator_recovery(current)

        if self.own_generator_demand:
            if self.generator_stop_requested:
                self._tick_generator_stop(current)
                if self.own_generator_demand:
                    self._tick_generator_keepalive(current)
                return
            if not self._fresh(MessageKind.GENERATOR_DEMAND_STATUS, current):
                view = self.views["generator"]
                if (
                    self._fresh(MessageKind.GENERATOR_STATUS_1, current)
                    and not self._generator_running()
                ):
                    self._release_generator(
                        "stale demand status while generator stopped",
                        now=current,
                    )
                    view.phase = ControlPhase.FAULT
                    view.fault = (
                        "generator demand status became stale before run; "
                        "bridge demand released"
                    )
                    return
                self._begin_generator_stop(
                    "generator demand status became stale; unload required",
                    now=current,
                )
                self._tick_generator_stop(current)
                if self.own_generator_demand:
                    self._tick_generator_keepalive(current)
                return
            if (
                self.generator_start_deadline is not None
                and current >= self.generator_start_deadline
            ):
                self._release_generator("generator start timeout", now=current)
                view = self.views["generator"]
                view.phase = ControlPhase.FAULT
                view.fault = "generator failed to start before timeout"
                return
            if (
                self.generator_max_run_deadline is not None
                and current >= self.generator_max_run_deadline
            ):
                self._begin_generator_stop(
                    "maximum run time reached; unload required",
                    now=current,
                )
                self._tick_generator_stop(current)
                if self.own_generator_demand:
                    self._tick_generator_keepalive(current)
                return
            self._tick_generator_keepalive(current)

        if (
            self.generator_cleanup_required
            and not self.own_generator_demand
            and self.generator_release_retry_at is not None
            and current >= self.generator_release_retry_at
        ):
            if self.generator_release_attempts <= self.config.max_retries:
                self._send_generator_release(current)
            else:
                self.generator_release_retry_at = None
                view = self.views["generator"]
                view.phase = ControlPhase.FAULT
                view.fault = (
                    "generator release is unconfirmed; cleanup marker retained"
                )

    def begin_generator_shutdown(self, *, now: Optional[float] = None) -> bool:
        """Begin a controlled daemon shutdown without stopping under load.

        Return True only when this process no longer owns an asserted demand.
        If the generator is running or status is uncertain, the process must
        remain alive while the ordinary unload/cooldown state machine runs.
        A forced process death leaves the persistent cleanup marker in place.
        """

        current = self._now(now)
        self.generator_shutdown_requested = True
        if not self.own_generator_demand:
            return True
        if (
            self._fresh(MessageKind.GENERATOR_STATUS_1, current)
            and not self._generator_running()
        ):
            self._release_generator(
                "daemon shutdown after generator stopped", now=current
            )
            return True
        self._begin_generator_stop(
            "daemon shutdown requested; unload required before exit",
            now=current,
        )
        return False

    @property
    def generator_shutdown_ready(self) -> bool:
        return self.generator_shutdown_requested and not self.own_generator_demand

    def recover_generator_for_startup(
        self, *, now: Optional[float] = None
    ) -> None:
        """Recover a demand marker without an immediate, blind Release.

        Fresh demand and engine status decide whether the marker is already
        stale, can be released while stopped, or must pass unload/cooldown.
        No Start or Release frame is emitted by this method itself.
        """

        current = self._now(now)
        self._require_feature("generator_demand")
        self.generator_cleanup_required = True
        self.generator_demand_hook(True)
        self.own_generator_demand = False
        self.generator_recovery_pending = True
        self.generator_release_attempts = 0
        self.generator_release_retry_at = None
        self.generator_keepalive_at = None
        view = self.views["generator"]
        view.requested = False
        view.phase = ControlPhase.RECOVERING
        view.fault = "waiting for fresh generator demand and engine status"

    def release_autofill_for_shutdown(self) -> None:
        """Best-effort stop for a fill started by this process."""

        if self.autofill_cleanup_required:
            self._send(autofill_command(self._source(), False))
            self.own_autofill_request = False
            self.autofill_max_run_deadline = None

    def recover_autofill_for_startup(
        self, *, now: Optional[float] = None
    ) -> None:
        """Stop an AutoFill left active across an unclean process exit.

        The persistent marker is intentionally retained until authoritative
        TM-102 status reports Off; sending a frame is not treated as proof.
        """

        current = self._now(now)
        self._require_feature("autofill_stop")
        self.autofill_cleanup_required = True
        self.autofill_active_hook(True)
        self._begin_acknowledged_command(
            name="autofill",
            desired=False,
            frame=autofill_command(self._source(), False),
            now=current,
        )
