import logging
import re
import subprocess
from pathlib import Path
from typing import Annotated, Optional

import typer

from gibby import logic, snapshot_behavior

from . import _utils as utils

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help='Commands regarding snapshots. Try "gibby snapshot help".',
)

logger = logging.getLogger()


@app.command()
def help() -> None:
    """
    Displays help about snapshots.
    """

    print("During `gibby backup`, gibby saves a snapshot of your uncommitted changes.")
    print(
        f"You can control the behavior of specific files by marking them with the `{logic.SNAPSHOT_ATTRIBUTE}` git attribute."
    )
    print("Setting git attributes is done in the `.gitattributes` file or in `.git/info/attributes` like so:")
    print(f"  foo.txt {logic.SNAPSHOT_ATTRIBUTE}={snapshot_behavior.SnapshotBehavior.only_if_staged}")
    print("Run `git help attributes` for further explanation about git attributes.")
    print()
    print(f"The {logic.SNAPSHOT_ATTRIBUTE} attribute may have the following values:")
    for val in snapshot_behavior.SnapshotBehavior:
        print(f"* {val}{' (default)' if val == snapshot_behavior.DEFAULT else ''}")
        print(f"    {val.get_description()}")
    print(f"Any other value is treated as '{snapshot_behavior.DEFAULT}'.")
    print()
    print(
        "You may use the `gibby snapshot list` command to view all files with the attribute set in a given repository."
    )


@app.command("list")
def cli_list(
    source_directory: Annotated[
        Optional[Path],
        typer.Argument(help="The directory to list the snapshot for. Defaults to the current working directory."),
    ] = None,
    ignore_dir: Annotated[
        Optional[re.Pattern[str]], typer.Option(help=utils.IGNORE_DIRECTORY_REGEX_HELP, click_type=utils.RegexParser())
    ] = None,
) -> None:
    """
    Lists all files that have the gibby-snapshot attribute, and their corresponding attribute value.
    """

    utils.ensure_git_installed()
    source_directory = source_directory or Path(".")
    repositories = list(logic.yield_git_repositories(source_directory, ignore_dir))
    if not repositories:
        logger.error(f"No git repositories were found under '{source_directory}'.")
        exit(1)

    count = 0
    for repository in repositories:
        try:
            for file, attribute_value in logic.yield_paths_with_snapshot_attribute(repository, ignore_dir):
                print(f"{file} - {attribute_value}")
                count += 1
        except subprocess.CalledProcessError as ex:
            logger.error(f"{ex.cmd[0]} exited with status {ex.returncode}.")
            exit(ex.returncode)
    print(f"{count} files total.")
