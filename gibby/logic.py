import itertools
import logging
import os
import re
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any, Optional

from .git import Git, git_directory_name
from .remote_url import RemoteUrl

logger = logging.getLogger()


SNAPSHOT_ATTRIBUTE = "gibby-snapshot"
SNAPSHOT_ATTRIBUTE_FORCE = "force"
GIBBY_SNAPSHOT_BRANCH = "gibby_internal/snapshot"
MAX_GIT_ADD_ARGUMENTS = 32


def is_path_ignored(path: Path, ignore_path_regex: re.Pattern) -> bool:
    path_string = str(path).replace(os.sep, "/")
    return bool(ignore_path_regex.match(path_string))


def yield_non_git_files(root: Path, ignore_dir_regex: Optional[re.Pattern] = None) -> Generator[Path, None, None]:
    queue = [root]
    while queue:
        current_directory = queue.pop()
        if current_directory.name == git_directory_name:
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


def yield_files_with_snapshot_attribute(
    repository: Path, ignore_dir_regex: Optional[re.Pattern] = None
) -> Generator[tuple[Path, str], None, None]:
    """
    Yields files and directories in the given repository that have the force snapshot attribute.
    """

    logger.info(f"Searching for snapshot files in '{repository}'")

    def encode_path(path: Path) -> bytes:
        result = str(path.relative_to(repository))
        if path.is_dir() and not result.endswith("/"):
            result += "/"
        return result.encode()

    stdin = b"\0".join(map(encode_path, yield_non_git_files(repository, ignore_dir_regex)))
    stdout = Git(repository).run_with_stdin(stdin, "check-attr", "--stdin", "-z", SNAPSHOT_ATTRIBUTE)
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
            yield (repository / path.decode(), value)


def do_backup(repository: Path, remote: RemoteUrl) -> None:
    logger.info(f"Backing up '{repository}' to '{remote}'")

    original_permissions = repository.stat().st_mode & 0o777
    remote.mkdirs(original_permissions)
    remote.init_git_bare_if_needed()

    files_with_snapshot_attribute = list(yield_files_with_snapshot_attribute(repository))
    git = Git(repository)
    current_branch_or_commit = git.get_current_branch()
    if is_detached_head := current_branch_or_commit is None:
        current_branch_or_commit = git.get_current_commit_hash()
        serialized_branch_name = ":" + current_branch_or_commit
    else:
        serialized_branch_name = current_branch_or_commit

    git("branch", "-f", "--no-track", GIBBY_SNAPSHOT_BRANCH)
    git.checkout(GIBBY_SNAPSHOT_BRANCH)
    git("commit", "--no-verify", "--allow-empty", "-m", f"staged@{serialized_branch_name}")
    git("add", ".")
    files_to_force_snapshot = filter(lambda pair: pair[1] == SNAPSHOT_ATTRIBUTE_FORCE, files_with_snapshot_attribute)
    for batch in yield_batches(files_to_force_snapshot, MAX_GIT_ADD_ARGUMENTS):
        git("add", "--force", batch)
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
        git("push", "--all", "--force", remote.raw_url)
    finally:
        git("branch", "--delete", "--force", GIBBY_SNAPSHOT_BRANCH)


def do_restore(remote: RemoteUrl, repository: Path) -> None:
    pass
