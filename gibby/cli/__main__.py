import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from .. import remote_url
from ..git import Git
from ..logic import do_backup
from . import snapshot

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
) -> None:
    """
    Recursively backs up the given file tree to the given remote.
    """
    
    try:
        backup_root_url = remote_url.parse(backup_root)
        Git().git_executable
    except ValueError as ex:
        logger.error(ex)
        exit(1)
    found_any = False
    for git_directory in source_directory.rglob(Git().git_directory_name):
        if not git_directory.is_dir():
            continue
        found_any = True
        repository = git_directory.parent
        if repository == source_directory:
            remote_subdirectory = Path(repository.name)
        else:
            remote_subdirectory = repository.relative_to(source_directory)
        do_backup(repository, backup_root_url.joinpath(remote_subdirectory))
    if not found_any:
        logger.error(f"No git repositories were found under '{source_directory}'.")
        exit(1)


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
