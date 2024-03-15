import itertools
import logging
import os
import re
import subprocess
from collections.abc import Generator, Iterator
from contextlib import contextmanager
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
            # TODO
            # queue.extend([current_directory / "hooks", current_directory / "info"])
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


class AbortOperationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def __str__(self) -> str:
        return self.message


@contextmanager
def _do_snapshot(repository: Path) -> Generator[None, None, None]:
    git = Git(repository)
    checks_to_error_messages = {
        git.is_ongoing_cherry_pick: "cherry pick",
        git.is_ongoing_merge: "merge",
        git.is_ongoing_rebase: "rebase",
        git.is_ongoing_revert: "revert",
    }
    for check in checks_to_error_messages:
        if check():
            raise AbortOperationError(f"Can't snapshot during an in-progress {checks_to_error_messages[check]}.")
    current_branch_or_commit = git.get_current_branch()
    if is_detached_head := current_branch_or_commit is None:
        current_branch_or_commit = git.get_current_commit_hash()
        serialized_branch_name = ":" + current_branch_or_commit
    else:
        serialized_branch_name = current_branch_or_commit
        if current_branch_or_commit == GIBBY_SNAPSHOT_BRANCH:
            raise AbortOperationError(
                f"Refusing to snapshot a repository with branch '{GIBBY_SNAPSHOT_BRANCH}' checked-out."
            )

    files_with_snapshot_attribute = list(yield_paths_with_snapshot_attribute(repository))
    git("branch", "-f", "--no-track", GIBBY_SNAPSHOT_BRANCH)
    git("symbolic-ref", "HEAD", f"refs/heads/{GIBBY_SNAPSHOT_BRANCH}")
    git("commit", "--no-verify", "--allow-empty", "-m", f"staged@{serialized_branch_name}")
    git("add", ".")
    files_to_force_snapshot = filter(lambda pair: pair[1] == SnapshotBehavior.force, files_with_snapshot_attribute)
    for batch in yield_batches((pair[0] for pair in files_to_force_snapshot), MAX_GIT_ADD_ARGUMENTS):
        git("add", "--force", "--", *(str(path) for path in batch))
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
            raise AbortOperationError(f"Remote '{remote}' does not seem to exist!")
        logger.info("Connectivity check passed")

    with _do_snapshot(repository):
        git = Git(repository)
        git("push", "--all", "--force", "--", remote)
        local_branches = set(git.get_local_branches())
        remote_branches = git.get_remote_branches(remote)
        for remote_branch in remote_branches:
            if remote_branch not in local_branches:
                logger.info(f"Deleting branch {remote_branch} from backup because it no longer exists")
                git("push", remote, "--delete", remote_branch)


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
    ORIGIN_NAME = "gibby-origin"
    git("clone", "--no-hardlinks", "--origin", ORIGIN_NAME, remote, ".")
    current_branch = git.get_current_branch()
    logger.info("Creating local branches...")
    for branch in git.get_remote_branches(remote):
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]
        if branch == current_branch:
            continue
        git("branch", branch, "--track", f"remotes/{ORIGIN_NAME}/{branch}")
    if current_branch != GIBBY_SNAPSHOT_BRANCH:
        logger.warning(
            f"Expected current branch to be {GIBBY_SNAPSHOT_BRANCH}, but was {current_branch}. Concluding restore with a simple clone."
        )
    else:
        logger.info("Restoring index state from snapshot")
        original_branch = (
            git.get_commit_message(GIBBY_SNAPSHOT_BRANCH).strip("\n").split("@")[1]
        )  # e.g. unstaged@main -> main
        git("symbolic-ref", "HEAD", f"refs/heads/{original_branch}")
        git("reset", f"{GIBBY_SNAPSHOT_BRANCH}^")
        git("reset", "--soft", f"{GIBBY_SNAPSHOT_BRANCH}^^")
    logger.info(f"Obliterating branch {GIBBY_SNAPSHOT_BRANCH}")
    try:
        git("branch", "--delete", "--force", GIBBY_SNAPSHOT_BRANCH)
    except subprocess.CalledProcessError:
        logger.warning(f"Failed deleting branch {GIBBY_SNAPSHOT_BRANCH}. Giving up obliteration.")
    else:
        git("reflog", "expire", "--expire-unreachable=now")
        git("gc", "--prune=now")
    pass
    logger.info(f"Removing remote {ORIGIN_NAME}")
    git("remote", "remove", ORIGIN_NAME)
    logger.info(f"Restore '{remote}' complete.")


def yield_git_repositories(
    root: Path, ignore_dir_regex: Optional[re.Pattern[str]] = None
) -> Generator[Path, None, None]:
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
        if (directory / git_directory_name).exists():
            yield directory
            continue
        queue.extend(x for x in directory.iterdir() if x.is_dir())


def backup(source_directory: Path, backup_root: RemoteUrl, ignore_dir: Optional[re.Pattern[str]] = None) -> None:
    """
    Recursively backs up the given file tree to the given remote.

    :raises AbortOperationError: When thrown, some repository within the source directory could not (and was not) backed up. It was left in the same state as nothing was performed.
    """

    repositories = list(yield_git_repositories(source_directory, ignore_dir))
    if not repositories:
        raise AbortOperationError(f"No git repositories were found under '{source_directory}'.")
    for repository in repositories:
        if repository == source_directory:
            remote_subdirectory = Path(repository.name)
        else:
            remote_subdirectory = repository.relative_to(source_directory)
        remote_path = backup_root.joinpath(remote_subdirectory)
        original_permissions = repository.stat().st_mode & 0o777
        remote_path.mkdirs(original_permissions)
        remote_path.init_git_bare_if_needed(GIBBY_SNAPSHOT_BRANCH)
        backup_single(repository, remote_path.raw_url, test_connectivity=False)
