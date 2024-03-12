import logging
import re
from collections.abc import Generator
from pathlib import Path
from typing import Optional

import click

from .. import remote_url
from ..git import get_git_executable, git_directory_name
from ..logic import is_path_ignored

logger = logging.getLogger()


IGNORE_DIRECTORY_REGEX_HELP = """Directories whose path matches this regex will be excluded, along with their descendants.
    Paths are separated with '/' and are relative to the root directory.
    For example, '.*/foo' ignores all directories named foo, whereas 'foo' only ignores the top-level foo directory."""


class RemoteUrlParser(click.ParamType):
    name = "url_like"

    def __init__(self, tip: Optional[str] = None) -> None:
        super().__init__()
        self.tip = tip

    def convert(
        self,
        value: str,
        param: Optional[click.Parameter],
        ctx: Optional[click.Context],
    ) -> remote_url.RemoteUrl:
        try:
            return remote_url.parse(value)
        except ValueError as ex:
            logger.error(ex)
            if self.tip is not None:
                logger.info(self.tip)
            exit(1)


class RegexParser(click.ParamType):
    name = "regex"

    def convert(
        self,
        value: str,
        param: Optional[click.Parameter],
        ctx: Optional[click.Context],
    ) -> re.Pattern[str]:
        try:
            return re.compile(value)
        except re.error as ex:
            logger.error(f"Invalid regex pattern '{ex.pattern!r}': {ex.msg}")
            exit(1)


def ensure_git_installed() -> None:
    try:
        get_git_executable()
    except ValueError as ex:
        logger.error(ex)
        exit(1)


def yield_git_repositories(
    root: Path, ignore_dir_regex: Optional[re.Pattern[str]] = None
) -> Generator[Path, None, None]:
    """
    Performs a breadth-first search for git repositories within and including root.
    """

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
