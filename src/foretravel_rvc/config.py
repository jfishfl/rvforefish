"""Runtime configuration with fail-closed transmission gates."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from typing import Any, Dict, Optional


_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class FeatureGate:
    enabled: bool = False
    payload_validated: bool = False

    @classmethod
    def from_dict(cls, value: Any, name: str) -> "FeatureGate":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("feature {!r} must be an object".format(name))
        allowed = {"enabled", "payload_validated"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "unknown keys for feature {}: {}".format(
                    name, ", ".join(sorted(unknown))
                )
            )
        enabled = value.get("enabled", False)
        validated = value.get("payload_validated", False)
        if not isinstance(enabled, bool) or not isinstance(validated, bool):
            raise ValueError("feature gates must be booleans")
        return cls(enabled=enabled, payload_validated=validated)


@dataclass(frozen=True)
class RuntimeConfig:
    interface: str = "vecan0"
    tm102_source: int = 0xFA
    source_address: Optional[int] = None
    monitor_only: bool = True
    genset_device_instance: int = 40
    switch_device_instance: int = 50
    temperature_device_instance_base: int = 60
    water_pump: FeatureGate = field(default_factory=FeatureGate)
    autofill_stop: FeatureGate = field(default_factory=FeatureGate)
    autofill_start: FeatureGate = field(default_factory=FeatureGate)
    generator_demand: FeatureGate = field(default_factory=FeatureGate)
    generator_orphan_demand_test_passed: bool = False
    generator_unload_test_passed: bool = False
    autofill_interlocks_verified: bool = False
    source_label_writes: bool = False
    authoritative_source_signal_verified: bool = False
    temporary_source_label_heuristic: bool = False
    source_label_delay_seconds: float = 60.0
    source_label_stable_seconds: float = 5.0
    source_label_status_stale_seconds: float = 90.0
    automatic_current_limit_switching: bool = False
    generator_current_limit_amps: float = 50.0
    shore_current_limit_fallback_amps: float = 30.0
    ack_timeout_seconds: float = 2.0
    max_retries: int = 2
    status_max_age_seconds: float = 7.0
    generator_cooldown_seconds: float = 300.0
    generator_keepalive_seconds: float = 60.0
    generator_start_timeout_seconds: float = 120.0
    generator_max_run_seconds: Optional[float] = None
    generator_unloaded_current_threshold_amps: Optional[float] = None
    generator_unloaded_confirm_seconds: float = 30.0
    generator_stop_escalation_seconds: Optional[float] = None
    autofill_max_run_seconds: Optional[float] = None

    @property
    def transmission_armed(self) -> bool:
        return not self.monitor_only and self.source_address is not None

    @property
    def can_tx_armed(self) -> bool:
        return self.transmission_armed and any(
            self.feature_can_transmit(name)
            for name in (
                "water_pump",
                "autofill_stop",
                "autofill_start",
                "generator_demand",
            )
        )

    def feature_can_transmit(self, name: str) -> bool:
        gate = getattr(self, name)
        return self.transmission_armed and gate.enabled and gate.payload_validated

    def validate(self) -> None:
        boolean_fields = (
            "monitor_only",
            "generator_orphan_demand_test_passed",
            "generator_unload_test_passed",
            "autofill_interlocks_verified",
            "source_label_writes",
            "authoritative_source_signal_verified",
            "temporary_source_label_heuristic",
            "automatic_current_limit_switching",
        )
        for name in boolean_fields:
            if not isinstance(getattr(self, name), bool):
                raise ValueError("{} must be boolean".format(name))

        def require_integer(name: str, value: Any) -> None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("{} must be an integer".format(name))

        def require_number(name: str, value: Any) -> None:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError("{} must be a finite number".format(name))

        if (
            not isinstance(self.interface, str)
            or not self.interface
            or not _INTERFACE_RE.fullmatch(self.interface)
        ):
            raise ValueError("invalid SocketCAN interface name")
        require_integer("tm102_source", self.tm102_source)
        if not 0 <= self.tm102_source <= 0xFD:
            raise ValueError("tm102_source must be 0..253")
        if self.source_address is not None:
            require_integer("source_address", self.source_address)
            if not 0 <= self.source_address <= 0xFD:
                raise ValueError("source_address must be 0..253")
            if self.source_address == self.tm102_source:
                raise ValueError("bridge and TM-102 source addresses must differ")
        require_integer("genset_device_instance", self.genset_device_instance)
        if not 0 <= self.genset_device_instance <= 32767:
            raise ValueError("invalid genset device instance")
        require_integer("switch_device_instance", self.switch_device_instance)
        if not 0 <= self.switch_device_instance <= 32767:
            raise ValueError("invalid switch device instance")
        require_integer(
            "temperature_device_instance_base",
            self.temperature_device_instance_base,
        )
        if not 0 <= self.temperature_device_instance_base <= 32517:
            raise ValueError("invalid temperature device instance base")
        if not self.monitor_only and self.source_address is None:
            raise ValueError("source_address is required before TX can be armed")

        for name in (
            "water_pump",
            "autofill_stop",
            "autofill_start",
            "generator_demand",
        ):
            gate = getattr(self, name)
            if not isinstance(gate, FeatureGate):
                raise ValueError("{} must be a feature gate".format(name))
            if not isinstance(gate.enabled, bool) or not isinstance(
                gate.payload_validated, bool
            ):
                raise ValueError("feature gates must be booleans")
            if gate.enabled and not gate.payload_validated:
                raise ValueError(
                    "{} cannot be enabled until payload_validated is true".format(
                        name
                    )
                )

        if self.generator_demand.enabled and not self.generator_orphan_demand_test_passed:
            raise ValueError(
                "generator demand requires a passed orphan-demand failure test"
            )
        if self.generator_demand.enabled and self.generator_max_run_seconds is None:
            raise ValueError(
                "generator demand requires an explicit maximum run time"
            )
        if self.generator_demand.enabled and not self.generator_unload_test_passed:
            raise ValueError(
                "generator demand requires a passed unloaded-cooldown test"
            )
        if (
            self.generator_demand.enabled
            and self.generator_unloaded_current_threshold_amps is None
        ):
            raise ValueError(
                "generator demand requires an explicit unloaded-current threshold"
            )
        if (
            self.generator_demand.enabled
            and self.generator_stop_escalation_seconds is None
        ):
            raise ValueError(
                "generator demand requires an explicit stop escalation timer"
            )
        if self.autofill_start.enabled and not self.autofill_interlocks_verified:
            raise ValueError(
                "autofill start requires verified level/pressure/pump interlocks"
            )
        if self.autofill_start.enabled and not self.autofill_stop.enabled:
            raise ValueError(
                "autofill start requires the autofill stop gate to be enabled"
            )
        if self.autofill_start.enabled and self.autofill_max_run_seconds is None:
            raise ValueError(
                "autofill start requires an explicit maximum run time"
            )
        if (
            self.source_label_writes
            and not self.authoritative_source_signal_verified
            and not self.temporary_source_label_heuristic
        ):
            raise ValueError(
                "source-label writes require an authoritative transfer-source "
                "signal or the explicit temporary heuristic"
            )
        if self.temporary_source_label_heuristic and not self.source_label_writes:
            raise ValueError(
                "temporary source-label heuristic requires source_label_writes"
            )
        if (
            self.automatic_current_limit_switching
            and not self.temporary_source_label_heuristic
        ):
            raise ValueError(
                "automatic current-limit switching requires the temporary "
                "source-label heuristic"
            )

        require_number("ack_timeout_seconds", self.ack_timeout_seconds)
        require_integer("max_retries", self.max_retries)
        require_number("status_max_age_seconds", self.status_max_age_seconds)
        require_number("generator_cooldown_seconds", self.generator_cooldown_seconds)
        require_number("generator_keepalive_seconds", self.generator_keepalive_seconds)
        require_number(
            "generator_start_timeout_seconds",
            self.generator_start_timeout_seconds,
        )
        require_number(
            "generator_unloaded_confirm_seconds",
            self.generator_unloaded_confirm_seconds,
        )
        for name in (
            "source_label_delay_seconds",
            "source_label_stable_seconds",
            "source_label_status_stale_seconds",
            "generator_current_limit_amps",
            "shore_current_limit_fallback_amps",
        ):
            require_number(name, getattr(self, name))
        for name in (
            "generator_max_run_seconds",
            "generator_unloaded_current_threshold_amps",
            "generator_stop_escalation_seconds",
            "autofill_max_run_seconds",
        ):
            value = getattr(self, name)
            if value is not None:
                require_number(name, value)

        if self.ack_timeout_seconds <= 0:
            raise ValueError("ack_timeout_seconds must be positive")
        if not 0 <= self.max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")
        if self.status_max_age_seconds <= 0:
            raise ValueError("status_max_age_seconds must be positive")
        if self.generator_cooldown_seconds < 300:
            raise ValueError("generator cooldown cannot be shorter than 300 seconds")
        if not 10 <= self.generator_keepalive_seconds <= 120:
            raise ValueError(
                "generator demand keepalive must be between 10 and 120 seconds"
            )
        if not 30 <= self.generator_start_timeout_seconds <= 600:
            raise ValueError("generator start timeout must be between 30 and 600 seconds")
        if self.generator_max_run_seconds is not None:
            if not 600 <= self.generator_max_run_seconds <= 86400:
                raise ValueError(
                    "generator maximum run time must be between 600 and 86400 seconds"
                )
        if self.generator_unloaded_current_threshold_amps is not None:
            if not 0 <= self.generator_unloaded_current_threshold_amps <= 100:
                raise ValueError(
                    "generator unloaded-current threshold must be between 0 and 100 amps"
                )
        if not 5 <= self.generator_unloaded_confirm_seconds <= 300:
            raise ValueError(
                "generator unloaded confirmation must be between 5 and 300 seconds"
            )
        if self.generator_stop_escalation_seconds is not None:
            minimum = (
                self.generator_unloaded_confirm_seconds
                + self.generator_cooldown_seconds
                + 60
            )
            if not minimum <= self.generator_stop_escalation_seconds <= 3600:
                raise ValueError(
                    "generator stop escalation timer must allow unload confirmation, "
                    "cooldown, and 60 seconds of margin, and cannot exceed 3600 seconds"
                )
        if self.autofill_max_run_seconds is not None:
            if not 60 <= self.autofill_max_run_seconds <= 86400:
                raise ValueError(
                    "autofill maximum run time must be between 60 and 86400 seconds"
                )
        if not 30 <= self.source_label_delay_seconds <= 300:
            raise ValueError(
                "source-label delay must be between 30 and 300 seconds"
            )
        if not 2 <= self.source_label_stable_seconds <= 30:
            raise ValueError(
                "source-label stable time must be between 2 and 30 seconds"
            )
        if not 75 <= self.source_label_status_stale_seconds <= 300:
            raise ValueError(
                "source-label status stale time must be between 75 and 300 seconds"
            )
        if not 5 <= self.shore_current_limit_fallback_amps <= 30:
            raise ValueError(
                "shore current-limit fallback must be between 5 and 30 amps"
            )
        if not 30 <= self.generator_current_limit_amps <= 50:
            raise ValueError(
                "generator current limit must be between 30 and 50 amps"
            )
        if (
            self.generator_current_limit_amps
            <= self.shore_current_limit_fallback_amps
        ):
            raise ValueError(
                "generator current limit must exceed the shore fallback"
            )

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "RuntimeConfig":
        if not isinstance(value, dict):
            raise ValueError("configuration root must be an object")
        allowed = {
            "interface",
            "tm102_source",
            "source_address",
            "monitor_only",
            "genset_device_instance",
            "switch_device_instance",
            "temperature_device_instance_base",
            "features",
            "generator_orphan_demand_test_passed",
            "generator_unload_test_passed",
            "autofill_interlocks_verified",
            "source_label_writes",
            "authoritative_source_signal_verified",
            "temporary_source_label_heuristic",
            "source_label_delay_seconds",
            "source_label_stable_seconds",
            "source_label_status_stale_seconds",
            "automatic_current_limit_switching",
            "generator_current_limit_amps",
            "shore_current_limit_fallback_amps",
            "ack_timeout_seconds",
            "max_retries",
            "status_max_age_seconds",
            "generator_cooldown_seconds",
            "generator_keepalive_seconds",
            "generator_start_timeout_seconds",
            "generator_max_run_seconds",
            "generator_unloaded_current_threshold_amps",
            "generator_unloaded_confirm_seconds",
            "generator_stop_escalation_seconds",
            "autofill_max_run_seconds",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "unknown configuration keys: {}".format(
                    ", ".join(sorted(unknown))
                )
            )
        features = value.get("features", {})
        if not isinstance(features, dict):
            raise ValueError("features must be an object")
        feature_names = {
            "water_pump",
            "autofill_stop",
            "autofill_start",
            "generator_demand",
        }
        unknown_features = set(features) - feature_names
        if unknown_features:
            raise ValueError(
                "unknown features: {}".format(
                    ", ".join(sorted(unknown_features))
                )
            )

        kwargs = {key: val for key, val in value.items() if key != "features"}
        for name in feature_names:
            kwargs[name] = FeatureGate.from_dict(features.get(name), name)
        config = cls(**kwargs)
        config.validate()
        return config


def load_config(path: str) -> RuntimeConfig:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    return RuntimeConfig.from_dict(value)
