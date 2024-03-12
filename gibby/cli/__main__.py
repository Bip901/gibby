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
            help="This directory will be searched recursively for git repositories, which will be backed up, except for repositories excluded by --ignore-dir."
        ),
    ],
    backup_root: Annotated[
        remote_url.RemoteUrl,
        typer.Argument(
            help="The local file path or URL to back up to. For example: C:/Backups. Subdirectories will be created as necessary.",
            click_type=utils.RemoteUrlParser(tip="Tip: Try using `backup-single`, which supports more URL schemes."),
        ),
    ],
    ignore_dir: Annotated[
        Optional[re.Pattern[str]], typer.Option(help=utils.IGNORE_DIRECTORY_REGEX_HELP, click_type=utils.RegexParser())
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
        remote_path = backup_root.joinpath(remote_subdirectory)
        original_permissions = repository.stat().st_mode & 0o777
        remote_path.mkdirs(original_permissions)
        remote_path.init_git_bare_if_needed()
        logic.do_backup(repository, remote_path.raw_url, snapshot=True, test_connectivity=False)


@app.command()
def backup_single(
    source_directory: Annotated[
        Path,
        typer.Argument(help="This git repository will be backed up."),
    ],
    backup_url: Annotated[
        str,
        typer.Argument(
            help="The URL to back up to, in a format `git push` would understand (see: `git help push`, section GIT URLS).",
        ),
    ],
) -> None:
    """
    Backs up a single repository.
    As opposed 'backup', 'backup-single' supports any URL format your git supports, because it performs no extra logic on the remote.
    """

    utils.ensure_git_installed()
    logic.do_backup(source_directory, backup_url, snapshot=True, test_connectivity=True)


@app.command()
def restore(
    backup_path: Annotated[
        remote_url.RemoteUrl,
        typer.Argument(
            help="The local file path or URL to restore from. For example: C:/Backups/Foo.",
            click_type=utils.RemoteUrlParser(),
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
