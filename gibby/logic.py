from __future__ import annotations

import itertools
import logging
import os
import re
import subprocess
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .git import GIT_BARE_SENTRY_FILE, Git, GitOngoingOperation, git_directory_name
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
    root: Path, ignore_dir_regex: re.Pattern[str] | None = None
) -> Generator[Path, None, None]:
    """
    Performs breadth-first search for all descendant paths which aren't git-internal files.
    """

    queue = [root]
    while queue:
        current_directory = queue.pop()
        if current_directory.name == git_directory_name:
            # Presumably these are the only directories within .git the user might want to back up.
            # git disallows adding files from the .git directory, even with --force, so these require special treatment.
            # TODO
            # queue.extend(d for d in (current_directory / "hooks", current_directory / "info") if d.is_dir())
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
    repository: Path, ignore_dir_regex: re.Pattern[str] | None = None
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


def yield_git_repositories(root: Path, ignore_dir_regex: re.Pattern[str] | None = None) -> Generator[Path, None, None]:
    """
    Performs a breadth-first search for git repositories within and including root.
    """

    queue = [root]
    while queue:
        directory = queue.pop()
        if ignore_dir_regex is not None:
            if is_path_ignored(directory.relative_to(root), ignore_dir_regex):
                logger.info(f"Skipping directory {directory}")
                continue
        if (directory / git_directory_name).is_dir():
            yield directory
            continue
        queue.extend(x for x in directory.iterdir() if x.is_dir())


class AbortOperationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass
class RepoState:
    # These fields are mutually exclusive, at least one will be None
    current_branch: str | None
    current_commit_hash: str | None
    ###
    is_orphan: bool

    @property
    def is_detached_head(self) -> bool:
        return self.current_branch is None and self.current_commit_hash is not None

    def serialize(self) -> str:
        if self.current_branch is None:
            assert self.current_commit_hash is not None  # Relax type checker
            result = ":" + self.current_commit_hash
        else:
            result = self.current_branch
        result += f" orphan?{1 if self.is_orphan else 0}"
        return result

    @classmethod
    def deserialize(cls, serialized: str) -> RepoState:
        fields = serialized.split(" ")
        is_orphan = fields[1].endswith("1")
        if fields[0].startswith(":"):
            return cls(None, fields[0][1:], is_orphan)
        else:
            return cls(fields[0], None, is_orphan)


def _apply_snapshot(git: Git, original_repo_state: RepoState) -> None:
    if original_repo_state.is_detached_head:
        # return to detached head state
        assert original_repo_state.current_commit_hash is not None  # Relax type checker
        git("checkout", "--detach")
        git("reset", "--soft", original_repo_state.current_commit_hash)
    else:
        # checkout original branch without changing the working tree
        git("symbolic-ref", "HEAD", f"refs/heads/{original_repo_state.current_branch}")
    # -> At this point, all changes from the snapshot (including ones that were unstaged) are staged.
    git("reset", f"{GIBBY_SNAPSHOT_BRANCH}^")
    # -> At this point, all unstaged changes from the snapshot are unstaged, but staged changes from the snapshot are not present in the index at all
    if original_repo_state.is_orphan:
        # re-orphan branch
        git("update-ref", "-d", "HEAD")
    else:
        git("reset", "--soft", f"{GIBBY_SNAPSHOT_BRANCH}^^")


@contextmanager
def _record_snapshot(repository: Path) -> Generator[None, None, None]:
    git = Git(repository)
    for operation in GitOngoingOperation:
        if git.is_ongoing_operation(operation):
            raise AbortOperationError(f"Can't snapshot during an in-progress {operation.name}.")
    current_branch = git.get_current_branch()
    if current_branch is None:  # detached head
        is_orphan = False
        original_repo_state = RepoState(
            current_branch=None, current_commit_hash=git.get_current_commit_hash(), is_orphan=is_orphan
        )
    else:
        is_orphan = git.is_orphan(current_branch)
        original_repo_state = RepoState(current_branch=current_branch, current_commit_hash=None, is_orphan=is_orphan)
        if current_branch == GIBBY_SNAPSHOT_BRANCH:
            raise AbortOperationError(
                f"Refusing to snapshot a repository with branch '{GIBBY_SNAPSHOT_BRANCH}' checked-out."
            )

    files_with_snapshot_attribute = list(yield_paths_with_snapshot_attribute(repository))
    if not is_orphan:
        git("branch", "-f", "--no-track", GIBBY_SNAPSHOT_BRANCH)
    git("symbolic-ref", "HEAD", f"refs/heads/{GIBBY_SNAPSHOT_BRANCH}")
    git("commit", "--no-verify", "--allow-empty", "-m", "staged snapshot")
    git("add", ".")
    files_to_force_snapshot = (pair[0] for pair in files_with_snapshot_attribute if pair[1] == SnapshotBehavior.force)
    for batch in yield_batches(files_to_force_snapshot, MAX_GIT_ADD_ARGUMENTS):
        git("add", "--force", "--", *(str(path) for path in batch))
    git("commit", "--no-verify", "--allow-empty", "-m", f"unstaged snapshot\n{original_repo_state.serialize()}")
    # We've modified the original repo while creating the snapshot...
    # Good thing we've just made a snapshot to restore from :)
    _apply_snapshot(git, original_repo_state)
    try:
        yield None
    finally:
        git("branch", "--delete", "--force", GIBBY_SNAPSHOT_BRANCH)


def backup_single(repository: Path, remote: str, test_connectivity: bool) -> None:
    """
    Backs up a single repository.

    :param repository: The local path of the repository to back up.
    :param remote: The git remote URL.
    :param test_connectivity: If true, connectivity to the remote will be tested before performing any action.

    :raises ValueError:
    :raises AbortOperationError: When thrown, the repository could not (and was not) backed up. It was left in the same state as nothing was performed.
    """

    if remote.startswith("-"):
        raise ValueError("Remote must not begin with '-'. For local paths that start with '-', use './-' instead.")
    logger.info(f"Backing up '{repository}' to '{remote}'")

    if test_connectivity:
        logger.info(f"Checking connectivity with remote '{remote}'")
        if not Git(repository).does_remote_exist(remote):
            raise AbortOperationError(f"Remote '{remote}' does not seem to exist / be a git repository!")
        logger.info("Connectivity check passed")

    with _record_snapshot(repository):
        git = Git(repository)
        # Push all branches and delete old remote branches
        git("push", "--all", "--force", "--", remote)
        local_branches = set(git.get_local_branches())
        remote_branches = set(git.get_remote_branches(remote))
        for extra_branch in remote_branches.difference(local_branches):
            logger.info(f"Deleting branch {extra_branch} from backup because it no longer exists")
            git("push", remote, "--delete", extra_branch)
        # Push all tags and delete old remote tags
        git("push", "--tags", "--force", "--", remote)
        local_tags = set(git.get_local_tags())
        remote_tags = set(git.get_remote_tags(remote))
        for extra_tag in remote_tags.difference(local_tags):
            logger.info(f"Deleting tag {extra_tag} from backup because it no longer exists")
            git("push", remote, "--delete", extra_tag)


def restore_single(remote: str, restore_to: Path, drop_snapshot: bool) -> None:
    """
    Restores a single repository.

    :raises ValueError:
    """

    if remote.startswith("-"):
        raise ValueError("Remote must not begin with '-'. For local paths that start with '-', use './-' instead.")
    if not restore_to.exists():
        logger.info(f"Creating empty directory '{restore_to}'")
        restore_to.mkdir(exist_ok=True)
    if not restore_to.is_dir():
        raise ValueError(f"'{restore_to}' is not a directory.")
    if len(list(restore_to.iterdir())) > 0:
        raise ValueError(f"Refusing to restore into non-empty directory '{restore_to}'")
    git = Git(restore_to)
    origin_name = "gibby-origin"
    git("clone", "--no-hardlinks", "--origin", origin_name, remote, ".")
    current_branch = git.get_current_branch()
    logger.info("Creating local branches...")
    for branch in git.get_remote_branches(remote):
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]
        if branch == current_branch:
            continue
        git("branch", branch, "--track", f"remotes/{origin_name}/{branch}")
    if current_branch != GIBBY_SNAPSHOT_BRANCH:
        logger.warning(
            f"Expected current branch to be {GIBBY_SNAPSHOT_BRANCH}, but was {current_branch}. Skipping snapshot restoration."
        )
    elif not drop_snapshot:
        logger.info("Restoring index state from snapshot")
        second_commit_message_line = git.get_commit_message(GIBBY_SNAPSHOT_BRANCH).rstrip("\n").splitlines()[1]
        original_repo_state = RepoState.deserialize(second_commit_message_line)
        _apply_snapshot(git, original_repo_state)
    logger.info(f"Obliterating branch {GIBBY_SNAPSHOT_BRANCH}")
    try:
        git("branch", "--delete", "--force", GIBBY_SNAPSHOT_BRANCH)
    except subprocess.CalledProcessError:
        logger.warning(f"Failed deleting branch {GIBBY_SNAPSHOT_BRANCH}. Giving up obliteration.")
    else:
        git("reflog", "expire", "--expire-unreachable=now")
        git("gc", "--prune=now")
    logger.info(f"Removing remote {origin_name}")
    git("remote", "remove", origin_name)
    logger.info(f"Restore '{remote}' complete.")


def backup(source_directory: Path, backup_root: RemoteUrl, ignore_dir: re.Pattern[str] | None) -> None:
    """
    Recursively backs up the given file tree to the given remote.
    By the end of this function, the directory tree in backup_root will be a partial mirror copy of source_directory (that is, only containing the .git directories found and not excluded)

    :raises AbortOperationError: When thrown, some repository within the source directory could not (and was not) backed up. It was left in the same state as nothing was performed.
    """

    repositories = list(yield_git_repositories(source_directory, ignore_dir))
    if not repositories:
        raise AbortOperationError(f"No git repositories were found under '{source_directory}'.")
    for repository in repositories:
        remote_subdirectory = repository.relative_to(source_directory)
        remote_path = backup_root.joinpath(remote_subdirectory)
        original_permissions = repository.stat().st_mode & 0o777
        remote_path.mkdirs(original_permissions)
        remote_path.init_git_bare_if_needed(GIBBY_SNAPSHOT_BRANCH)
        backup_single(repository, remote_path.raw_url, test_connectivity=False)


def restore(backup_root: RemoteUrl, to_directory: Path, drop_snapshot: bool) -> None:
    """
    Recursively restores a backed-up file tree.

    :raises ValueError:
    """

    if to_directory.exists():
        if not to_directory.is_dir():
            raise ValueError(f"'{to_directory}' is not a directory!")
        if next(to_directory.iterdir(), None) is not None:
            raise ValueError(f"Refusing to restore to non-empty directory '{to_directory}'")
    else:
        to_directory.mkdir()

    queue = [backup_root]
    while queue:
        remote_directory = queue.pop()
        local_subdirectory = to_directory / remote_directory.relative_to(backup_root)
        if remote_directory.joinpath(GIT_BARE_SENTRY_FILE).is_file():
            restore_single(str(remote_directory), local_subdirectory, drop_snapshot)
        else:
            local_subdirectory.mkdir(exist_ok=True)
            queue.extend(x for x in remote_directory.iterdir() if x.is_dir())
