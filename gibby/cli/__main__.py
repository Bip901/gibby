import logging
import re
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from gibby import logic, remote_url

from . import _utils as utils
from . import snapshot

app = typer.Typer(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]})
app.add_typer(snapshot.app, name="snapshot")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stderr)
stream_handler.setFormatter(logging.Formatter("{asctime} {levelname[0]}\t{message}", style="{", datefmt="%H:%M:%S"))
logger.addHandler(stream_handler)


@app.command()
def backup(
    source_directory: Annotated[
        Path,
        typer.Argument(
            help="This directory will be searched recursively for git repositories, which will be backed up, except for repositories excluded by --ignore-dir."
        ),
    ],
    backup_root: Annotated[
        remote_url.RemoteUrl,
        typer.Argument(
            help="The local file path or URL to back up to. For example: C:/Backups. This directory and subdirectories will be created if necessary.",
            click_type=utils.RemoteUrlParser(tip="Tip: Try using `backup-single`, which supports more URL schemes."),
        ),
    ],
    ignore_dir: Annotated[
        Optional[re.Pattern[str]], typer.Option(help=utils.IGNORE_DIRECTORY_REGEX_HELP, click_type=utils.RegexParser())
    ] = None,
) -> None:
    """
    Recursively searches for git directories and backs them up to the given remote, which will become a partial mirror of the source directory.
    """

    utils.ensure_git_installed()
    try:
        logic.backup(source_directory, backup_root, ignore_dir)
    except logic.AbortOperationError as ex:
        logger.error(ex.message)
        exit(1)


@app.command()
def backup_single(
    source_directory: Annotated[
        Path,
        typer.Argument(help="This git repository will be backed up."),
    ],
    backup_url: Annotated[
        str,
        typer.Argument(
            help="The URL or path to back up to, in a format `git push` would understand (see: `git help push`, section GIT URLS).",
        ),
    ],
) -> None:
    """
    Backs up a single repository.
    As opposed 'backup', 'backup-single' supports any URL format your git supports, because it performs no extra logic on the remote.
    """

    utils.ensure_git_installed()
    try:
        logic.backup_single(source_directory, backup_url, test_connectivity=True)
    except (logic.AbortOperationError, ValueError) as ex:
        logger.error(ex)
        exit(1)


@app.command()
def restore_single(
    backup_url: Annotated[
        str,
        typer.Argument(
            help="The URL or path to restore from, in a format `git push` would understand (see: `git help push`, section GIT URLS).",
        ),
    ],
    restore_to: Annotated[
        Path,
        typer.Argument(
            help="The directory to restore into. The directory will be created if necessary, and it must be empty."
        ),
    ],
    drop_snapshot: Annotated[
        bool,
        typer.Argument(
            help="Whether to ignore the snapshot data in the backup (true) or include it in the restoration (false)."
        ),
    ] = False,
) -> None:
    """
    Restores a single repository.
    As opposed 'restore', 'restore-single' supports any URL format your git supports, because it performs no extra logic on the remote.
    """

    utils.ensure_git_installed()
    try:
        logic.restore_single(backup_url, restore_to, drop_snapshot)
    except ValueError as ex:
        logger.error(ex)
        exit(1)


@app.command()
def restore(
    backup_root: Annotated[
        remote_url.RemoteUrl,
        typer.Argument(
            help="The local file path or URL to restore from. For example: C:/Backups/Foo.",
            click_type=utils.RemoteUrlParser(),
        ),
    ],
    restore_to: Annotated[
        Path,
        typer.Argument(
            help="The local directory to restore to. The directory will be created if necessary, and it must be empty."
        ),
    ],
    drop_snapshot: Annotated[
        bool,
        typer.Argument(
            help="Whether to ignore the snapshot data in the backup (true) or include it in the restoration (false)."
        ),
    ] = False,
) -> None:
    """
    Recursively restores a backed-up file tree created with `backup`.
    """
    utils.ensure_git_installed()
    try:
        logic.restore(backup_root, restore_to, drop_snapshot)
    except ValueError as ex:
        logger.error(ex)
        exit(1)


if __name__ == "__main__":
    app()
