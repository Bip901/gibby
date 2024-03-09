"""
Commands regarding snapshots.
Gibby saves files marked with the git attribute "gibby-snapshot" exactly as they are in the working directory, even if they're ignored by git.
See "git help attributes" for help on marking files with attributes.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Annotated, Optional

import typer

from .. import logic
from . import _utils as utils

app = typer.Typer(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]}, help=__doc__)

logger = logging.getLogger()


@app.command("list")
def cli_list(
    source_directory: Annotated[
        Optional[Path],
        typer.Argument(help="The directory to list the snapshot for. Defaults to the current working directory."),
    ] = None,
    ignore_dir: Annotated[Optional[re.Pattern], typer.Option(help=utils.IGNORE_DIRECTORY_REGEX_HELP, parser=utils.regex)] = None,
) -> None:
    """
    Lists all files that will be included in the snapshot.
    """

    utils.ensure_git_installed()
    source_directory = source_directory or Path(".")
    repositories = list(utils.yield_git_repositories(source_directory, ignore_dir))
    if not repositories:
        logger.error(f"No git repositories were found under '{source_directory}'.")
        exit(1)

    count = 0
    for repository in repositories:
        try:
            for file in logic.yield_snapshot_files(repository):
                print(file)
                count += 1
        except subprocess.CalledProcessError as ex:
            logger.error(f"{ex.cmd[0]} exited with status {ex.returncode}.")
            exit(ex.returncode)
    print(f"{count} files total.")
