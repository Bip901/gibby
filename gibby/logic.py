import itertools
import logging
import os
import re
from collections.abc import Generator, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any, Optional

from .git import Git, git_directory_name
from .remote_url import RemoteUrl
from .snapshot_behavior import SnapshotBehavior

logger = logging.getLogger()


SNAPSHOT_ATTRIBUTE = "gibby-snapshot"
GIBBY_SNAPSHOT_BRANCH = "gibby_internal/snapshot"
MAX_GIT_ADD_ARGUMENTS = 32


def is_path_ignored(path: Path, ignore_path_regex: re.Pattern[str]) -> bool:
    path_string = str(path).replace(os.sep, "/")
    return bool(ignore_path_regex.match(path_string))


def yield_possibly_snapshotted_paths(
    root: Path, ignore_dir_regex: Optional[re.Pattern[str]] = None
) -> Generator[Path, None, None]:
    """
    Performs breadth-first search for all descendant paths which aren't git-internal files.
    """

    queue = [root]
    while queue:
        current_directory = queue.pop()
        if current_directory.name == git_directory_name:
            # Presumably these are the only two directories within .git the user might want to back up.
            # git disallows adding files from the .git directory, even with --force, so these require special treatment.
            # Backing up the "objects" directory, for example, is unsupported and undefined in gibby.
            queue.extend([current_directory / "hooks", current_directory / "info"])
            continue
        if ignore_dir_regex is not None and is_path_ignored(current_directory.relative_to(root), ignore_dir_regex):
            logger.info(f"Skipping directory {current_directory}")
            continue
        for file in current_directory.iterdir():
            yield file
            if file.is_dir():
                queue.append(file)


def yield_batches(iterator: Iterator[Any], batch_size: int) -> Generator[list[Any], None, None]:
    while chunk := list(itertools.islice(iterator, batch_size)):
        yield chunk


def yield_paths_with_snapshot_attribute(
    repository: Path, ignore_dir_regex: Optional[re.Pattern[str]] = None
) -> Generator[tuple[Path, SnapshotBehavior], None, None]:
    """
    Yields files and directories in the given repository that have a snapshot attribute.
    """

    logger.info(f"Searching for '{SNAPSHOT_ATTRIBUTE}' attributes in '{repository}'")

    def encode_path(path: Path) -> bytes:
        result = str(path.relative_to(repository))
        if path.is_dir() and not result.endswith("/"):
            result += "/"
        return result.encode()

    stdin = b"\0".join(map(encode_path, yield_possibly_snapshotted_paths(repository, ignore_dir_regex)))
    stdout = Git(repository)("check-attr", "--stdin", "-z", SNAPSHOT_ATTRIBUTE, stdin=stdin)
    i = 0
    while i < len(stdout):
        try:
            next_separator = stdout.index(b"\0", i)
        except ValueError:
            break
        path = stdout[i:next_separator]
        i = stdout.index(b"\0", next_separator) + 1  # Skip the "tag" field
        i = stdout.index(b"\0", i) + 1
        try:
            next_separator = stdout.index(b"\0", i)
        except ValueError:
            next_separator = len(stdout)
        value = stdout[i:next_separator].decode()
        i = next_separator + 1
        if value != "unspecified":
            value_enum = SnapshotBehavior.from_str(value)
            yield (repository / path.decode(), value_enum)


class SnapshotError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


@contextmanager
def do_snapshot(repository: Path) -> Generator[None, None, None]:
    git = Git(repository)
    checks_to_error_messages = {
        git.is_ongoing_cherry_pick: "cherry pick",
        git.is_ongoing_merge: "merge",
        git.is_ongoing_rebase: "rebase",
        git.is_ongoing_revert: "revert",
    }
    for check in checks_to_error_messages:
        if check():
            raise SnapshotError(f"Can't snapshot during an in-progress {checks_to_error_messages[check]}.")
    current_branch_or_commit = git.get_current_branch()
    if is_detached_head := current_branch_or_commit is None:
        current_branch_or_commit = git.get_current_commit_hash()
        serialized_branch_name = ":" + current_branch_or_commit
    else:
        serialized_branch_name = current_branch_or_commit
        if current_branch_or_commit == GIBBY_SNAPSHOT_BRANCH:
            raise SnapshotError(f"Refusing to snapshot a repository with branch '{GIBBY_SNAPSHOT_BRANCH}' checked-out.")

    files_with_snapshot_attribute = list(yield_paths_with_snapshot_attribute(repository))
    git("branch", "-f", "--no-track", GIBBY_SNAPSHOT_BRANCH)
    git("symbolic-ref", "HEAD", f"refs/heads/{GIBBY_SNAPSHOT_BRANCH}")
    git("commit", "--no-verify", "--allow-empty", "-m", f"staged@{serialized_branch_name}")
    git("add", ".")
    files_to_force_snapshot = filter(lambda pair: pair[1] == SnapshotBehavior.force, files_with_snapshot_attribute)
    for batch in yield_batches((pair[0] for pair in files_to_force_snapshot), MAX_GIT_ADD_ARGUMENTS):
        git("add", "--force", *(str(path) for path in batch))
    git("commit", "--no-verify", "--allow-empty", "-m", f"unstaged@{serialized_branch_name}")
    if is_detached_head:
        # return to detached head state
        git.checkout(current_branch_or_commit)
    else:
        # checkout original branch without changing the working tree
        git("symbolic-ref", "HEAD", f"refs/heads/{current_branch_or_commit}")
    # All changes are now staged, including those that were unstaged before.
    git("reset", f"{GIBBY_SNAPSHOT_BRANCH}^")
    git("reset", "--soft", f"{GIBBY_SNAPSHOT_BRANCH}^^")
    try:
        yield None
    finally:
        git("branch", "--delete", "--force", GIBBY_SNAPSHOT_BRANCH)


def do_backup(repository: Path, remote: str, snapshot: bool, test_connectivity: bool) -> None:
    logger.info(f"Backing up '{repository}' to '{remote}'")

    if test_connectivity:
        logger.info(f"Checking connectivity with remote '{remote}'")
        if not Git(repository).does_remote_exist(remote):
            logger.error(f"Remote '{remote}' does not seem to exist! Skipping '{repository}'.")
            return
        logger.info("Connectivity check passed")

    snapshot_cleaner: AbstractContextManager[Any] = do_snapshot(repository) if snapshot else nullcontext()
    try:
        with snapshot_cleaner:
            Git(repository)("push", "--all", "--force", remote)
    except SnapshotError as ex:
        logger.error(ex.message + f" Skipping '{repository}'.")


def do_restore(remote: RemoteUrl, repository: Path) -> None:
    pass
