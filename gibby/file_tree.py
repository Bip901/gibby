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

    def _insert_descendant(self, path: Path, should_snapshot: bool) -> None:
        for descendant in self.rebel_descendants:
            if path.is_relative_to(descendant.path):
                descendant._insert_descendant(path, should_snapshot)
                return
        if should_snapshot != self.should_snapshot:
            self.rebel_descendants.append(FileTree(path, should_snapshot, []))

    @classmethod
    def from_list(cls, root: Path, values: Iterable[tuple[Path, SnapshotBehavior]]) -> FileTree:
        """Constructs a FileTree from a flat list of paths to snapshot behaviors.
        Assumes any non-listed paths are marked as only_if_staged.

        :param root: The root of the file tree.
        :param values: A list of tuples (path, SnapshotBehavior) where 'path' is a descendant of 'root'.
        """
        result = cls(root, False, [])
        values_list = list(values)
        values_list.sort(key=lambda x: len(x[0].parts))
        for value in values_list:
            if value[1] == SnapshotBehavior.force:
                result._insert_descendant(value[0], True)
            elif value[1] == SnapshotBehavior.only_if_staged_ignore_parent:
                result._insert_descendant(value[0], False)
        return result

    def walk(self) -> Generator[tuple[bool, list[Path]], None, None]:
        """Yields alternating lists of files and directories that should be force snapshotted (True) or force removed (False)."""
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
                if queue:
                    queue.append(None)
                continue
            buffer.append(element.path)
            queue.extend(element.rebel_descendants)
