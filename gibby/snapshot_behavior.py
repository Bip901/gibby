from __future__ import annotations

from enum import Enum


class SnapshotBehavior(Enum):
    only_if_staged = 0
    force = 1

    def __str__(self) -> str:
        return self.name

    @classmethod
    def from_str(cls, string: str) -> SnapshotBehavior:
        try:
            return cls[string.casefold().replace("-", "_")]
        except KeyError:
            return DEFAULT


DEFAULT = SnapshotBehavior.only_if_staged
