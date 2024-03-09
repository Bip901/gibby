import logging
import re
from collections.abc import Generator
from pathlib import Path
from typing import Optional

from .. import remote_url
from ..git import Git
from ..logic import is_path_ignored

logger = logging.getLogger()


IGNORE_DIRECTORY_REGEX_HELP = """Directories whose path matches this regex will be excluded, along with their descendants.
    Paths are separated with '/' and are relative to the root directory.
    For example, '.*/foo' ignores all directories named foo, whereas 'foo' only ignores the top-level foo directory."""


def url_like(value: str) -> remote_url.RemoteUrl:
    """
    Parses a RemoteUrl argument from the CLI.
    Note: this function's name is shown to the user as the argument type.
    """
    try:
        return remote_url.parse(value)
    except ValueError as ex:
        logger.error(ex)
        exit(1)


def regex(value: str) -> re.Pattern:
    """
    Parses a regex argument from the CLI.
    Note: this function's name is shown to the user as the argument type.
    """
    try:
        return re.compile(value)
    except re.error as ex:
        logger.error(f"Invalid regex pattern '{ex.pattern}': {ex.msg}")
        exit(1)


def ensure_git_installed():
    try:
        Git().git_executable  # Ensure git is installed. If not, this raises ValueError.
    except ValueError as ex:
        logger.error(ex)
        exit(1)


def yield_git_repositories(root: Path, ignore_dir_regex: Optional[re.Pattern] = None) -> Generator[Path, None, None]:
    """
    Performs a breadth-first search for git repositories within and including root.
    """

    git_directory_name = Git().git_directory_name
    queue = [root]
    while queue:
        directory = queue.pop()
        if ignore_dir_regex is not None:
            if is_path_ignored(directory.relative_to(root), ignore_dir_regex):
                logger.info(f"Skipping directory {directory}")
                continue
        if (directory / git_directory_name).exists():
            yield directory
            continue
        queue.extend(x for x in directory.iterdir() if x.is_dir())
