import logging
import re
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from .. import logic, remote_url
from ..git import Git
from . import snapshot
from ._utils import IGNORE_DIRECTORY_REGEX_HELP, ensure_git_installed, regex_argument, yield_git_repositories

app = typer.Typer(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]})
app.add_typer(snapshot.app, name="snapshot")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stderr))


@app.command()
def backup(
    source_directory: Annotated[
        Path,
        typer.Argument(
            help="This directory will be searched recursively for git repositories, which will be backed up."
        ),
    ],
    backup_root: Annotated[
        str,
        typer.Argument(
            help="The URL of the root to back up to, for example: file:///C:/Backups. Subdirectories will be created as necessary. If the scheme is unspecified, defaults to file://."
        ),
    ],
    ignore_dir: Annotated[
        Optional[re.Pattern], typer.Option(help=IGNORE_DIRECTORY_REGEX_HELP, parser=regex_argument)
    ] = None,
) -> None:
    """
    Recursively backs up the given file tree to the given remote.
    """

    ensure_git_installed()
    try:
        backup_root_url = remote_url.parse(backup_root)
    except ValueError as ex:
        logger.error(ex)
        exit(1)
    try:
        ignore_path_regex = re.compile(ignore_dir) if ignore_dir else None
    except re.error as ex:
        logger.error(f"Invalid regex pattern '{ex.pattern}': {ex.msg}")
        exit(1)

    repositories = list(yield_git_repositories(source_directory, ignore_path_regex))
    if not repositories:
        logger.error(f"No git repositories were found under '{source_directory}'.")
        exit(1)
    for repository in repositories:
        if repository == source_directory:
            remote_subdirectory = Path(repository.name)
        else:
            remote_subdirectory = repository.relative_to(source_directory)
        logic.do_backup(repository, backup_root_url.joinpath(remote_subdirectory))


@app.command()
def restore(
    backup_path: Annotated[
        str,
        typer.Argument(
            help="The URL to restore from, for example: file:///C:/Backups/Foo. This follows the `git url` format (see: `git push --help`)."
        ),
    ],
    restore_to: Annotated[
        Optional[Path],
        typer.Argument(
            help="The directory to restore to - defaults to the current working directory. A subdirectory with the repo's name will be created."
        ),
    ] = None,
) -> None:
    try:
        backup_path_url = remote_url.parse(backup_path)
        Git().git_executable
    except ValueError as ex:
        logger.error(ex)
        exit(1)
    if not restore_to:
        restore_to = Path(".")


if __name__ == "__main__":
    app()
