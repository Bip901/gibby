import logging
import os
import re
from collections.abc import Generator
from pathlib import Path
from typing import Optional

from .git import Git
from .remote_url import RemoteUrl
from .state import State

logger = logging.getLogger()


SNAPSHOT_ATTRIBUTE = "gibby-snapshot"
BACKUP_SNAPSHOT_DIRECTORY = "snapshot"
BACKUP_GIT_DIRECTORY = "git"
STATE_FILE = "state.json"


def is_path_ignored(path: Path, ignore_path_regex: re.Pattern) -> bool:
    path_string = str(path).replace(os.sep, "/")
    return bool(ignore_path_regex.match(path_string))


def yield_non_git_files(root: Path, ignore_path_regex: Optional[re.Pattern] = None) -> Generator[Path, None, None]:
    git_directory_name = Git().git_directory_name
    queue = [root]
    while queue:
        current_directory = queue.pop()
        if current_directory.name == git_directory_name or (
            ignore_path_regex is not None and is_path_ignored(current_directory.relative_to(root), ignore_path_regex)
        ):
            continue
        for file in current_directory.iterdir():
            yield file
            if file.is_dir():
                queue.append(file)


def yield_snapshot_files(repository: Path) -> Generator[Path, None, None]:
    """
    Yields files and directories in the given repository that have the snapshot attribute.
    """

    logger.info(f"Searching for snapshot files in '{repository}'")
    stdin = b"\0".join(str(x.relative_to(repository)).encode() for x in yield_non_git_files(repository))
    stdout = Git().run_with_stdin(repository, stdin, "check-attr", "--stdin", "-z", SNAPSHOT_ATTRIBUTE)
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
            yield repository / path.decode()


def do_backup(repository: Path, remote: RemoteUrl) -> None:
    logger.info(f"Backing up '{repository}' to '{remote}'")

    original_permissions = repository.stat().st_mode & 0o777
    remote_repo = remote.joinpath(BACKUP_GIT_DIRECTORY)
    remote_repo.mkdirs(original_permissions)
    remote_repo.init_git_bare_if_needed()
    Git().run(repository, "push", "--all", "--force", remote_repo.raw_url)

    snapshot_dir = remote.joinpath(BACKUP_SNAPSHOT_DIRECTORY)
    snapshot_dir.mkdirs(original_permissions)
    for file in yield_snapshot_files(repository):
        pass  # TODO

    state = State(current_branch=Git().get_current_branch(repository))
    with remote.joinpath(STATE_FILE).open("w") as f:
        f.write(state.to_json().encode())


def do_restore(remote: RemoteUrl, repository: Path) -> None:
    pass
