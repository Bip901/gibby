import logging
from pathlib import Path
from typing import Generator

from .git import Git
from .remote_url import RemoteUrl
from .state import State

logger = logging.getLogger()


SNAPSHOT_ATTRIBUTE = "gibby-snapshot"
BACKUP_SNAPSHOT_DIRECTORY = "snapshot"
BACKUP_GIT_DIRECTORY = "git"
STATE_FILE = "state.json"


def yield_non_git_files(directory: Path) -> Generator[Path, None, None]:
    git_directory_name = Git().git_directory_name
    yield directory
    for file in directory.iterdir():
        if file.is_dir():
            if file.name == git_directory_name:
                continue
            yield from yield_non_git_files(file)
        yield file


def yield_snapshot_files(repository: Path) -> Generator[Path, None, None]:
    """
    Yields files and directories in the given repository that have the snapshot attribute.
    """

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
