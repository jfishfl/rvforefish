"""Venus OS runtime entry point."""

from __future__ import annotations

import argparse
import logging
import signal
import socket
import sys
import time

from .audit import AuditLogger
from .config import load_config
from .control import ControlEngine
from .dbus_export import DbusPublisher
from .decode import MessageKind, SUPPORTED_DGNS, decode_frame
from .model import SourceClass, classify_ac_source
from .socketcan import SocketCanTransport
from .state import GeneratorDemandMarker
from .victron import (
    GENERATOR_SOURCE,
    GeneratorSourceLabelHeuristic,
    VictronAcObserver,
    VictronCurrentLimitWriter,
    VictronInputModeController,
    VictronSourceLabelWriter,
    dbus_float_setter,
    dbus_getter,
    dbus_int_setter,
)


LOG = logging.getLogger("foretravel_rvc")


def find_nad_collision(items, source_address):
    """Return the RV-C device path already using the configured source."""

    if source_address is None or not isinstance(items, dict):
        return None
    for path, item in items.items():
        if not path.endswith("/Nad") or not isinstance(item, dict):
            continue
        value = item.get("Value")
        if isinstance(value, bool):
            continue
        try:
            nad = int(value)
        except (TypeError, ValueError):
            continue
        if nad == source_address:
            return path
    return None


def rvc_nad_collision(bus, source_address):
    if source_address is None:
        return None
    obj = bus.get_object("com.victronenergy.rvc.vecan0", "/")
    items = obj.GetItems(dbus_interface="com.victronenergy.BusItem")
    return find_nad_collision(items, source_address)


def autofill_startup_action(config, marker_exists: bool) -> str:
    """Return the only safe action for persistent AutoFill ownership state."""

    if not marker_exists:
        return "none"
    if config.feature_can_transmit("autofill_stop"):
        return "recover"
    return "refuse"


def generator_startup_action(config, marker_exists: bool) -> str:
    """Return the only safe action for persistent generator-demand state."""

    if not marker_exists:
        return "none"
    if config.feature_can_transmit("generator_demand"):
        return "recover"
    return "refuse"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safety-gated SilverLeaf TM-102 RV-C bridge"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--state-marker",
        default="/data/foretravel-rvc/state/own-generator-demand",
    )
    parser.add_argument(
        "--autofill-state-marker",
        default="/data/foretravel-rvc/state/own-autofill",
    )
    parser.add_argument("--validate-config", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser


def run(argv=None) -> int:
    args = build_argument_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config)
    if args.validate_config:
        LOG.info("configuration is valid; monitor_only=%s", config.monitor_only)
        return 0

    # Import the GLib bindings only on Venus OS.  Keeping imports out of the
    # pure modules allows the complete decision core to run in workstation CI.
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore
    from gi.repository import GLib  # type: ignore
    import dbus  # type: ignore

    DBusGMainLoop(set_as_default=True)
    system_bus = dbus.SystemBus()
    if config.transmission_armed:
        try:
            collision = rvc_nad_collision(
                system_bus,
                config.source_address,
            )
        except Exception:
            LOG.exception("unable to verify RV-C source-address ownership")
            return 3
        if collision is not None:
            LOG.critical(
                "configured RV-C source 0x%02X is already claimed at %s",
                config.source_address,
                collision,
            )
            return 3
    marker = GeneratorDemandMarker(args.state_marker)
    autofill_marker = GeneratorDemandMarker(args.autofill_state_marker)
    transport = SocketCanTransport(
        config.interface,
        read_only=not config.can_tx_armed,
        dgns=SUPPORTED_DGNS,
    )
    transport.open()
    audit = AuditLogger(LOG, tm102_source=config.tm102_source)

    def send_with_audit(frame):
        audit.transmit(frame)
        transport.send(frame)

    engine = ControlEngine(
        config,
        send_with_audit,
        generator_demand_hook=marker.set_active,
        autofill_active_hook=autofill_marker.set_active,
    )
    generator_recovery = generator_startup_action(config, marker.exists())
    if generator_recovery == "recover":
        LOG.warning(
            "recovering stale generator-demand marker; waiting for fresh "
            "demand and engine status before any release"
        )
        engine.recover_generator_for_startup()
    elif generator_recovery == "refuse":
        LOG.critical(
            "stale generator-demand marker exists but generator TX is not "
            "armed; refusing to start"
        )
        transport.close()
        return 2

    autofill_recovery = autofill_startup_action(
        config, autofill_marker.exists()
    )
    if autofill_recovery == "recover":
        LOG.warning(
            "recovering stale autofill marker with fail-safe stop"
        )
        engine.recover_autofill_for_startup()
    elif autofill_recovery == "refuse":
        LOG.critical(
            "stale autofill marker exists but autofill stop TX is not armed; "
            "refusing to start"
        )
        transport.close()
        return 2
    publisher = DbusPublisher(config, engine)
    try:
        getter = dbus_getter(system_bus)
        ac_observer = VictronAcObserver(getter)
    except Exception as error:
        LOG.warning("Victron AC observer could not open system bus: %s", error)

        def unavailable_ac_getter(service, path):
            raise RuntimeError("Victron system D-Bus unavailable")

        ac_observer = VictronAcObserver(unavailable_ac_getter)
    source_label_writer = None
    current_limit_writer = None
    input_mode_controller = None
    source_label_heuristic = None
    if (
        system_bus is not None
        and config.source_label_writes
        and config.temporary_source_label_heuristic
    ):
        try:
            source_label_writer = VictronSourceLabelWriter(
                getter,
                dbus_int_setter(system_bus),
            )
            if config.automatic_current_limit_switching:
                current_limit_writer = VictronCurrentLimitWriter(
                    getter,
                    dbus_float_setter(system_bus),
                )
            input_mode_controller = VictronInputModeController(
                source_label_writer,
                current_limit_writer,
                generator_current_limit_amps=(
                    config.generator_current_limit_amps
                ),
                shore_current_limit_fallback_amps=(
                    config.shore_current_limit_fallback_amps
                ),
            )
            source_label_heuristic = GeneratorSourceLabelHeuristic(
                delay_seconds=config.source_label_delay_seconds,
                stable_seconds=config.source_label_stable_seconds,
                status_stale_seconds=(
                    config.source_label_status_stale_seconds
                ),
            )
            for action in input_mode_controller.startup_safe():
                LOG.warning("%s at startup", action)
        except Exception:
            source_label_writer = None
            current_limit_writer = None
            input_mode_controller = None
            source_label_heuristic = None
            LOG.exception(
                "source-label shortcut disabled because Victron D-Bus setup failed"
            )
    next_source_poll = [0.0]
    shutdown_requested = [False]
    loop = GLib.MainLoop()

    def restore_shore_defaults(reason: str) -> bool:
        if input_mode_controller is None:
            return True
        try:
            for action in input_mode_controller.restore_grid():
                LOG.warning("%s: %s", action, reason)
            return True
        except Exception:
            LOG.exception("failed to restore shore defaults during %s", reason)
            return False

    def on_can_ready(fd, condition):
        if condition & (GLib.IO_ERR | GLib.IO_HUP | GLib.IO_NVAL):
            LOG.critical("SocketCAN watch failed: condition=%s", condition)
            loop.quit()
            return False
        try:
            frame = transport.recv(timeout=0.0)
        except (BlockingIOError, socket.timeout):
            return True
        except ValueError as error:
            LOG.debug("ignored non-data CAN frame: %s", error)
            return True
        except Exception:
            LOG.exception("SocketCAN receive failed")
            loop.quit()
            return False

        try:
            message = decode_frame(frame)
            if message is not None:
                audit.observe(message)
                engine.observe(message, now=frame.timestamp)
                publisher.publish(message, now=frame.timestamp)
        except ValueError as error:
            LOG.warning("invalid documented RV-C frame: %s", error)
        except Exception:
            LOG.exception("RV-C message processing failed")
        return True

    def on_tick():
        now = time.monotonic()
        try:
            engine.tick(now=now)
            publisher.refresh(now=now)
            if now >= next_source_poll[0]:
                next_source_poll[0] = now + 2.0
                ac_state = ac_observer.read()
                snapshot = engine.reducer.snapshot
                ats_seen = snapshot.last_seen.get(MessageKind.ATS_STATUS)
                generator_ac_seen = snapshot.last_seen.get(
                    MessageKind.GENERATOR_AC_STATUS_1
                )
                ats_fresh = (
                    ats_seen is not None and now - ats_seen <= 3.0
                )
                generator_ac_fresh = (
                    generator_ac_seen is not None
                    and now - generator_ac_seen <= 2.0
                )
                decision = classify_ac_source(
                    ve_bus_accepting_ac=ac_state.accepting_ac,
                    active_input_voltage=ac_state.active_input_voltage,
                    generator_voltage=snapshot.generator_ac_voltage,
                    generator_frequency=snapshot.generator_ac_frequency,
                    ats_source=snapshot.ats_source,
                    generator_demand=snapshot.generator_demand,
                    ats_fresh=ats_fresh,
                    generator_ac_fresh=generator_ac_fresh,
                    ve_bus_state_fresh=ac_state.fresh,
                )
                heuristic_decision = None
                if (
                    source_label_heuristic is not None
                    and input_mode_controller is not None
                ):
                    heuristic_decision = source_label_heuristic.update(
                        now=now,
                        generator_status_raw=snapshot.generator_status_raw,
                        generator_status_seen=snapshot.last_seen.get(
                            MessageKind.GENERATOR_STATUS_1
                        ),
                        ac_state=ac_state,
                    )
                    for action in input_mode_controller.apply(
                        heuristic_decision,
                        ac_state,
                    ):
                        LOG.warning("%s: %s", action, heuristic_decision.reason)
                temporary_generator_confirmed = bool(
                    heuristic_decision is not None
                    and heuristic_decision.target == GENERATOR_SOURCE
                    and ac_state.accepting_ac
                    and ac_state.both_legs_valid()
                )
                engine.observe_generator_input(
                    generator_source_confirmed=(
                        (
                            decision.source == SourceClass.GENERATOR
                            and decision.safe_to_write_victron_label
                        )
                        or temporary_generator_confirmed
                    ),
                    l1_current=ac_state.active_input_l1_current,
                    l2_current=ac_state.active_input_l2_current,
                    now=now,
                )
                publisher.publish_source_diagnostics(
                    decision,
                    ac_state,
                    ats_fresh=ats_fresh,
                    generator_ac_fresh=generator_ac_fresh,
                    now=now,
                )
            if shutdown_requested[0] and engine.generator_shutdown_ready:
                LOG.info("generator demand is safely released; exiting")
                loop.quit()
        except Exception:
            LOG.exception("periodic safety processing failed")
            restore_shore_defaults("periodic processing fault")
        return True

    def request_exit(*unused):
        if shutdown_requested[0]:
            return False
        shutdown_requested[0] = True
        try:
            engine.release_autofill_for_shutdown()
        except Exception:
            LOG.exception("failed to stop bridge-owned autofill on shutdown")
        try:
            if engine.begin_generator_shutdown():
                loop.quit()
            else:
                LOG.warning(
                    "shutdown deferred: retaining generator demand until "
                    "measured unload and cooldown complete"
                )
        except Exception:
            LOG.exception(
                "failed to begin safe generator shutdown; demand marker retained"
            )
        return False

    GLib.io_add_watch(
        transport.fileno(),
        GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP | GLib.IO_NVAL,
        on_can_ready,
    )
    GLib.timeout_add(500, on_tick)
    if hasattr(GLib, "unix_signal_add"):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, request_exit)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, request_exit)

    LOG.info(
        "starting on %s; monitor_only=%s; can_tx_armed=%s",
        config.interface,
        config.monitor_only,
        config.can_tx_armed,
    )
    try:
        loop.run()
    finally:
        restore_shore_defaults("service shutdown")
        try:
            engine.release_autofill_for_shutdown()
        except Exception:
            LOG.exception("failed to stop bridge-owned autofill on shutdown")
        if engine.own_generator_demand:
            LOG.critical(
                "process exiting while generator demand remains owned; no blind "
                "release sent and persistent recovery marker retained"
            )
        transport.close()
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
