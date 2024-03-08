import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

import remote_url
import typer

from .git import Git
from .remote_url import RemoteUrl

app = typer.Typer(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]})
# app.add_typer() # https://typer.tiangolo.com/tutorial/subcommands/add-typer/

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stderr))


def _backup(repository: Path, remote: RemoteUrl) -> None:
    logger.info(f"Backing up '{repository}' to '{remote}'")
    original_permissions = repository.stat().st_mode & 0o777
    remote.mkdirs(original_permissions)
    remote.init_git_bare_if_needed()
    Git().run(repository, "push", "--all", "--force", remote.raw_url)


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
    try:
        backup_root_url = remote_url.parse(backup_root)
        Git().git_executable
    except ValueError as ex:
        logger.error(ex)
        exit(1)
    found_any = False
    for descendant in source_directory.rglob(Git().git_directory_name):
        found_any = True
        repository = descendant.parent
        if repository == source_directory:
            remote_subdirectory = Path(repository.name)
        else:
            remote_subdirectory = repository.relative_to(source_directory)
        _backup(repository, backup_root_url.joinpath(remote_subdirectory))
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
