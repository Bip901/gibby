from __future__ import annotations

import itertools
import logging
import os
import re
import subprocess
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AbortOperationError, NonEmptyDirectoryError
from .file_tree import FileTree
from .git import GIT_BARE_SENTRY_FILE, Git, GitOngoingOperation, git_directory_name
from .remote_url import RemoteUrl
from .snapshot_behavior import SnapshotBehavior

logger = logging.getLogger()


SNAPSHOT_ATTRIBUTE = "gibby-snapshot"
GIBBY_SNAPSHOT_BRANCH = "gibby_internal/snapshot"
MAX_GIT_ADD_ARGUMENTS = 32


def is_path_ignored(path: Path | str, ignore_path_regex: re.Pattern[str] | None) -> bool:
    """Returns whether the given path should be ignored according to the given regex.

    :param path: A *relative* path.
    :param ignore_path_regex: The regex to use, or None to return False.
    """
    if ignore_path_regex is None:
        return False
    path_string = str(path).replace(os.sep, "/")
    return bool(ignore_path_regex.match(path_string))


def is_git_bare_directory(path_or_url: RemoteUrl | Path) -> bool:
    return path_or_url.joinpath(GIT_BARE_SENTRY_FILE).is_file()


def yield_possibly_snapshotted_paths(
    root: Path, ignore_dir_regex: re.Pattern[str] | None = None
) -> Generator[Path, None, None]:
    """
    Performs breadth-first search for all descendant paths which aren't git-internal files.
    """

    queue = [root]
    while queue:
        current_directory = queue.pop(0)
        if current_directory.name == git_directory_name:
            # Presumably these are the only directories within .git the user might want to back up.
            # git disallows adding files from the .git directory, even with --force, so these require special treatment.
            # TODO
            # queue.extend(d for d in (current_directory / "hooks", current_directory / "info") if d.is_dir())
            continue
        if is_path_ignored(current_directory.relative_to(root), ignore_dir_regex):
            logger.info(f"Skipping directory {current_directory}")
            continue
        for file in current_directory.iterdir():
            yield file
            if file.is_dir():
                queue.append(file)


def yield_batches(iterable: Iterable[Any], batch_size: int) -> Generator[list[Any], None, None]:
    iterable = iter(iterable)  # Make reading elements expendable
    while chunk := list(itertools.islice(iterable, batch_size)):
        yield chunk


def yield_paths_with_snapshot_attribute(
    repository: Path, ignore_dir_regex: re.Pattern[str] | None = None
) -> Generator[tuple[Path, SnapshotBehavior], None, None]:
    """
    Yields files and directories in the given repository that have a snapshot attribute.
    """

    logger.info(f"Searching for '{SNAPSHOT_ATTRIBUTE}' attributes in '{repository}'")
    paths_to_search = yield_possibly_snapshotted_paths(repository, ignore_dir_regex)
    for path, value in Git(repository).check_attr(SNAPSHOT_ATTRIBUTE, paths_to_search):
        yield (path, SnapshotBehavior.from_str(value))


def yield_git_repositories(root: Path, ignore_dir_regex: re.Pattern[str] | None = None) -> Generator[Path, None, None]:
    """
    Performs a breadth-first search for git repositories within and including root.
    """

    queue = [root]
    while queue:
        directory = queue.pop(0)
        if is_path_ignored(directory.relative_to(root), ignore_dir_regex):
            logger.info(f"Skipping directory {directory}")
            continue
        if (directory / git_directory_name).is_dir():
            yield directory
            continue
        queue.extend(x for x in directory.iterdir() if x.is_dir())


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
    file_tree = FileTree.from_list(repository, files_with_snapshot_attribute)
    for should_snapshot, paths in file_tree.walk():
        commands = ("add", "--force", "--") if should_snapshot else ("reset", "--")
        for batch in yield_batches(paths, MAX_GIT_ADD_ARGUMENTS):
            if batch:  # 'paths' is not supposed to be empty (thus neither should 'batch'), but check just in case there's a bug, because doing 'git reset' with no arguments is bad
                git(*commands, *(git.quote_pathspec(path) for path in batch))
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
        git("push", "--mirror", "--force", "--", remote)


def restore_single(remote: str, restore_to: Path, drop_snapshot: bool) -> None:
    """
    Restores a single repository.

    :raises ValueError:
    :raises NotADirectoryError:
    :raises NonEmptyDirectoryError:
    """

    if remote.startswith("-"):
        raise ValueError("Remote must not begin with '-'. For local paths that start with '-', use './-' instead.")
    if not restore_to.exists():
        logger.info(f"Creating empty directory '{restore_to}'")
        restore_to.mkdir(exist_ok=True)
    if not restore_to.is_dir():
        raise NotADirectoryError(f"'{restore_to}' is not a directory.")
    if len(list(restore_to.iterdir())) > 0:
        raise NonEmptyDirectoryError(f"Refusing to restore into non-empty directory '{restore_to}'")
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


def backup(
    source_directory: Path, backup_root: RemoteUrl, ignore_dir: re.Pattern[str] | None, delete_excess_repos: bool
) -> None:
    """
    Recursively searches for git directories and backs them up to the given remote.
    The directory structure is preserved in the backup, but files outside git repositories are not backed up.

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
    if delete_excess_repos:
        delete_excess_repositories(backup_root, source_directory, backup_root, ignore_dir)


def delete_excess_repositories(
    current_directory: RemoteUrl, source_root: Path, backup_root: RemoteUrl, ignore_dir: re.Pattern[str] | None
) -> None:
    for child in current_directory.iterdir():
        if not child.is_dir():
            continue
        relative_child_path = child.relative_to(backup_root)
        if is_path_ignored(relative_child_path, ignore_dir):
            continue
        if source_root.joinpath(relative_child_path).is_dir():
            if not is_git_bare_directory(child):
                delete_excess_repositories(child, source_root, backup_root, ignore_dir)
        else:
            logger.info(f"Deleting {child}")
            child.rmtree()


def restore(
    backup_root: RemoteUrl, to_directory: Path, drop_snapshot: bool, allow_non_empty_target: bool = False
) -> None:
    """
    Recursively restores a backed-up file tree.

    :raises NotADirectoryError:
    :raises NonEmptyDirectoryError:
    """

    if to_directory.exists():
        if not to_directory.is_dir():
            raise NotADirectoryError(f"'{to_directory}' is not a directory!")
        if not allow_non_empty_target and next(to_directory.iterdir(), None) is not None:
            raise NonEmptyDirectoryError(f"Refusing to restore to non-empty directory '{to_directory}'.", to_directory)
    else:
        to_directory.mkdir()

    queue = [backup_root]
    while queue:
        remote_directory = queue.pop(0)
        local_subdirectory = to_directory / remote_directory.relative_to(backup_root)
        if is_git_bare_directory(remote_directory):
            restore_single(str(remote_directory), local_subdirectory, drop_snapshot)
        else:
            local_subdirectory.mkdir(exist_ok=True)
            queue.extend(x for x in remote_directory.iterdir() if x.is_dir())
