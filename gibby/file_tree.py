from __future__ import annotations

from collections.abc import Generator, Iterable
from dataclasses import dataclass
from pathlib import Path

from .snapshot_behavior import SnapshotBehavior


@dataclass
class FileTree:
    path: Path
    should_snapshot: bool
    rebel_descendants: list[FileTree]
    """descendants with differing should_snapshot values."""

    def insert_descendant(self, path: Path, should_snapshot: bool) -> None:
        for descendant in self.rebel_descendants:
            if path.is_relative_to(descendant.path):
                descendant.insert_descendant(path, should_snapshot)
                return
        if should_snapshot != self.should_snapshot:
            self.rebel_descendants.append(FileTree(path, should_snapshot, []))

    @classmethod
    def from_list(cls, root: Path, values: Iterable[tuple[Path, SnapshotBehavior]]) -> FileTree:
        result = cls(root, False, [])
        values_list = list(values)
        values_list.sort(key=lambda x: len(x[0].parts))
        for value in values_list:
            if value[1] == SnapshotBehavior.force:
                result.insert_descendant(value[0], True)
            elif value[1] == SnapshotBehavior.only_if_staged_ignore_parent:
                result.insert_descendant(value[0], False)
        return result

    def walk(self) -> Generator[tuple[bool, list[Path]], None, None]:
        buffer: list[Path] = []
        queue: list[FileTree | None] = []
        if self.rebel_descendants:
            queue.extend(self.rebel_descendants)
            queue.append(None)
        should_snapshot = True
        while queue:
            element = queue.pop(0)
            if element is None:
                yield should_snapshot, buffer
                should_snapshot = not should_snapshot
                buffer = []
                continue
            buffer.append(element.path)
            if element.rebel_descendants:
                queue.extend(element.rebel_descendants)
                queue.append(None)
