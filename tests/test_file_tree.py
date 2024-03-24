from pathlib import Path

import pytest

from gibby.file_tree import FileTree
from gibby.snapshot_behavior import SnapshotBehavior


@pytest.mark.parametrize(
    "values,expected_walk_result",
    [
        (
            [],
            [],
        ),
        (
            [(".", SnapshotBehavior.force)],
            [(True, ["."])],
        ),
        (
            [
                ("a", SnapshotBehavior.force),
                ("b", SnapshotBehavior.force),
            ],
            [(True, ["a", "b"])],
        ),
        (
            [
                ("a", SnapshotBehavior.force),
                ("a/b", SnapshotBehavior.only_if_staged),
            ],
            [(True, ["a"])],
        ),
        (
            [
                ("a", SnapshotBehavior.force),
                ("a/b", SnapshotBehavior.only_if_staged_ignore_parent),
            ],
            [(True, ["a"]), (False, ["a/b"])],
        ),
        (
            [
                ("a", SnapshotBehavior.force),
                ("a/b", SnapshotBehavior.only_if_staged_ignore_parent),
                ("a/b/c", SnapshotBehavior.force),
            ],
            [(True, ["a"]), (False, ["a/b"]), (True, ["a/b/c"])],
        ),
        (
            [
                ("a", SnapshotBehavior.force),
                ("a/b", SnapshotBehavior.only_if_staged_ignore_parent),
                ("a/b/e", SnapshotBehavior.force),
                ("a/c", SnapshotBehavior.only_if_staged_ignore_parent),
                ("a/c/d", SnapshotBehavior.force),
                ("a/file", SnapshotBehavior.only_if_staged_ignore_parent),
            ],
            [(True, ["a"]), (False, ["a/b", "a/c", "a/file"]), (True, ["a/b/e", "a/c/d"])],
        ),
    ],
)
def test_walk(values: list[tuple[str, SnapshotBehavior]], expected_walk_result: list[tuple[bool, list[str]]]) -> None:
    base_path = Path("/tmp")
    file_tree = FileTree.from_list(base_path, [(base_path / pair[0], pair[1]) for pair in values])
    actual_walk_result = file_tree.walk()
    actual_walk_result_normalized = [(pair[0], set(pair[1])) for pair in actual_walk_result]
    expected_walk_result_normalized = [
        (pair[0], set((base_path / i) for i in pair[1])) for pair in expected_walk_result
    ]
    assert expected_walk_result_normalized == actual_walk_result_normalized
