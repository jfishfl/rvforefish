"""Minimal persistent marker for crash-safe generator-demand cleanup."""

from __future__ import annotations

import os
import time


class GeneratorDemandMarker:
    def __init__(self, path: str) -> None:
        self.path = path

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def set_active(self, active: bool) -> None:
        if not active:
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
            return

        parent = os.path.dirname(self.path) or "."
        os.makedirs(parent, mode=0o700, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="ascii") as handle:
            handle.write("active=1\n")
            handle.write("timestamp={}\n".format(int(time.time())))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
