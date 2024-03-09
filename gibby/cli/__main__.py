import logging
import re
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from .. import logic, remote_url
from . import _utils as utils
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
        remote_url.RemoteUrl,
        typer.Argument(
            help="The local file path or URL to back up to. For example: C:/Backups. Subdirectories will be created as necessary.",
            parser=utils.url_like,
        ),
    ],
    ignore_dir: Annotated[
        Optional[re.Pattern], typer.Option(help=utils.IGNORE_DIRECTORY_REGEX_HELP, parser=utils.regex)
    ] = None,
) -> None:
    """
    Recursively backs up the given file tree to the given remote.
    """

    utils.ensure_git_installed()
    repositories = list(utils.yield_git_repositories(source_directory, ignore_dir))
    if not repositories:
        logger.error(f"No git repositories were found under '{source_directory}'.")
        exit(1)
    for repository in repositories:
        if repository == source_directory:
            remote_subdirectory = Path(repository.name)
        else:
            remote_subdirectory = repository.relative_to(source_directory)
        logic.do_backup(repository, backup_root.joinpath(remote_subdirectory), ignore_dir)


@app.command()
def restore(
    backup_path: Annotated[
        remote_url.RemoteUrl,
        typer.Argument(
            help="The local file path or URL to restore from. For example: C:/Backups/Foo.",
            parser=utils.url_like,
        ),
    ],
    restore_to: Annotated[
        Optional[Path],
        typer.Argument(
            help="The directory to restore to - defaults to the current working directory. A subdirectory with the repo's name will be created."
        ),
    ] = None,
) -> None:
    utils.ensure_git_installed()
    if not restore_to:
        restore_to = Path(".")


if __name__ == "__main__":
    app()
