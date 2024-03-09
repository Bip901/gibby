"""
Commands regarding snapshots.
Gibby saves files marked with the git attribute "gibby-snapshot" exactly as they are in the working directory, even if they're ignored by git.
See "git help attributes" for help on marking files with attributes.
"""

from pathlib import Path
from typing import Annotated, Optional
from .. import logic
from ..git import Git
import subprocess
import typer
import logging

app = typer.Typer(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]}, help=__doc__)

logger = logging.getLogger()


@app.command("list")
def cli_list(
    source_directory: Annotated[
        Optional[Path],
        typer.Argument(help="The directory to list the snapshot for. Defaults to the current working directory."),
    ] = None,
) -> None:
    """
    Lists all files that will be included in the snapshot.
    """
    source_directory = source_directory or Path(".")
    
    repositories = list(d.parent for d in source_directory.rglob(Git().git_directory_name) if d.is_dir())
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
