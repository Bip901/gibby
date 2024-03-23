from __future__ import annotations

from enum import Enum


class SnapshotBehavior(Enum):
    only_if_staged = 0
    force = 1
    only_if_staged_ignore_parent = 2

    def __str__(self) -> str:
        return self.name.replace("_", "-")

    @classmethod
    def from_str(cls, string: str) -> SnapshotBehavior:
        try:
            return cls[string.casefold().replace("-", "_")]
        except KeyError:
            return DEFAULT

    def get_description(self) -> str:
        if self == SnapshotBehavior.only_if_staged:
            return "Only snapshot if this is already staged."
        elif self == SnapshotBehavior.force:
            return "Always snapshot this file. For directories, also includes all descendants."
        elif self == SnapshotBehavior.only_if_staged_ignore_parent:
            return "Only snapshot if this is already staged, even if an ancestor directory is set to 'force'."
        else:
            return ""


DEFAULT = SnapshotBehavior.only_if_staged
