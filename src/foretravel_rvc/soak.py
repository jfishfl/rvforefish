"""Deterministic validation of monitor-only soak samples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class SoakReport:
    samples: int
    duration_seconds: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    min_rss_kb: int
    max_rss_kb: int
    max_cpu_percent_one_core: float
    log_growth_kb: int
    app_growth_kb: int
    rx_error_delta: int
    tx_error_delta: int

    @property
    def passed(self) -> bool:
        return not self.errors


def _integer(row: Mapping[str, str], key: str) -> int:
    try:
        return int(row[key])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid or missing {!r}".format(key)) from error


def analyze_soak(
    rows: Iterable[Mapping[str, str]],
    *,
    min_samples: int = 288,
    expected_interval_seconds: int = 300,
    max_gap_slack_seconds: int = 90,
    clock_ticks_per_second: int = 100,
    max_log_kb: int = 1200,
    max_recovered_error_fraction: float = 0.001,
) -> SoakReport:
    samples: Sequence[Mapping[str, str]] = tuple(rows)
    if not samples:
        raise ValueError("soak contains no samples")
    if min_samples <= 0 or expected_interval_seconds <= 0:
        raise ValueError("sample and interval requirements must be positive")

    errors: list[str] = []
    warnings: list[str] = []
    if len(samples) < min_samples:
        errors.append(
            "only {} samples; {} required".format(len(samples), min_samples)
        )

    epochs = [_integer(row, "epoch_utc") for row in samples]
    rss = [_integer(row, "rss_kb") for row in samples]
    cpu = [_integer(row, "cpu_ticks") for row in samples]
    logs = [_integer(row, "log_kb") for row in samples]
    apps = [_integer(row, "app_kb") for row in samples]

    for index, row in enumerate(samples, start=1):
        if _integer(row, "service_up") != 1:
            errors.append("service down at sample {}".format(index))
        if row.get("can_state") != "ERROR-ACTIVE":
            errors.append(
                "CAN state {} at sample {}".format(
                    row.get("can_state", "missing"), index
                )
            )
        if _integer(row, "audit_tx_count") != 0:
            errors.append("bridge TX observed at sample {}".format(index))
        if _integer(row, "generator_owner_count") != 0:
            errors.append(
                "unexpected generator control owner at sample {}".format(index)
            )

    for left, right in zip(epochs, epochs[1:]):
        gap = right - left
        if gap <= 0:
            errors.append("timestamps are not strictly increasing")
            break
        if gap > expected_interval_seconds + max_gap_slack_seconds:
            errors.append("sample gap {} seconds exceeds limit".format(gap))

    for key in ("rx_dropped", "tx_dropped"):
        first = _integer(samples[0], key)
        last = _integer(samples[-1], key)
        if last > first:
            errors.append(
                "{} increased from {} to {}".format(key, first, last)
            )

    rx_error_delta = _integer(samples[-1], "rx_errors") - _integer(
        samples[0], "rx_errors"
    )
    tx_error_delta = _integer(samples[-1], "tx_errors") - _integer(
        samples[0], "tx_errors"
    )
    rx_packet_delta = max(
        0,
        _integer(samples[-1], "rx_packets")
        - _integer(samples[0], "rx_packets"),
    ) if "rx_packets" in samples[0] else 0
    tx_packet_delta = max(
        0,
        _integer(samples[-1], "tx_packets")
        - _integer(samples[0], "tx_packets"),
    ) if "tx_packets" in samples[0] else 0
    for direction, error_delta, packet_delta in (
        ("RX", rx_error_delta, rx_packet_delta),
        ("TX", tx_error_delta, tx_packet_delta),
    ):
        if error_delta > 0:
            fraction = error_delta / max(1, packet_delta)
            warnings.append(
                "{} recovered CAN errors increased by {} across {} frames "
                "({:.6%})".format(
                    direction, error_delta, packet_delta, fraction
                )
            )
            if fraction > max_recovered_error_fraction:
                errors.append(
                    "{} recovered CAN error rate {:.6%} exceeds {:.6%}".format(
                        direction, fraction, max_recovered_error_fraction
                    )
                )

    # Newer sampler files include controller-health counters.  Keep backward
    # compatibility with the in-progress first soak, but fail hard whenever
    # the CAN controller leaves normal operation or has to restart the bus.
    optional_hard_counters = (
        "can_restarts",
        "can_error_warn",
        "can_error_passive",
        "can_bus_off",
    )
    for key in optional_hard_counters:
        if key not in samples[0]:
            continue
        first = _integer(samples[0], key)
        last = _integer(samples[-1], key)
        if last > first or any(_integer(row, key) > first for row in samples):
            errors.append("{} increased from {} to {}".format(key, first, last))
    for key in ("berr_tx", "berr_rx"):
        if key in samples[0] and any(_integer(row, key) != 0 for row in samples):
            errors.append("non-zero {} observed".format(key))

    if max(logs) > max_log_kb:
        errors.append(
            "bounded log reached {} KiB (limit {})".format(
                max(logs), max_log_kb
            )
        )

    pids = {_integer(row, "pid") for row in samples}
    if len(pids) > 1:
        warnings.append("service PID changed during soak: {}".format(sorted(pids)))

    if any(_integer(row, "battery_service_count") < 6 for row in samples):
        warnings.append("fewer than six expected battery services were present")
    if any(_integer(row, "active_bms_present") != 1 for row in samples):
        warnings.append("active BMS was absent in one or more samples")

    max_cpu = 0.0
    for index in range(1, len(samples)):
        elapsed = epochs[index] - epochs[index - 1]
        ticks = cpu[index] - cpu[index - 1]
        # A PID change resets cumulative ticks; report it separately above.
        if elapsed > 0 and ticks >= 0:
            max_cpu = max(
                max_cpu,
                100.0 * ticks / (elapsed * clock_ticks_per_second),
            )

    return SoakReport(
        samples=len(samples),
        duration_seconds=epochs[-1] - epochs[0],
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        min_rss_kb=min(rss),
        max_rss_kb=max(rss),
        max_cpu_percent_one_core=max_cpu,
        log_growth_kb=logs[-1] - logs[0],
        app_growth_kb=apps[-1] - apps[0],
        rx_error_delta=rx_error_delta,
        tx_error_delta=tx_error_delta,
    )
