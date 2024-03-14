import logging
import re
from typing import Optional

import click

from .. import remote_url
from ..git import get_git_executable

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
