from __future__ import annotations

import abc
import urllib.parse
from pathlib import Path
from typing import BinaryIO


class RemoteUrl:
    def __init__(self, raw_url: str) -> None:
        self.raw_url = raw_url
        self._parse_result = urllib.parse.urlparse(raw_url)

    def joinpath(self, relative_path: str | Path) -> RemoteUrl:
        raw_url = self.raw_url
        if not raw_url.endswith("/"):
            raw_url += "/"  # Mark as a directory for proper urljoin
        new_url = urllib.parse.urljoin(raw_url, str(relative_path))
        return type(self)(new_url)

    def __str__(self) -> str:
        return self.raw_url

    @abc.abstractmethod
    def mkdirs(self, permissions: int = 0o777) -> None:
        """
        Creates this directory and all parent directories as necessary.

        :param permissions: The filesystem permissions to apply to all created directories. May be combined with this processe's umask.
        """

    @abc.abstractmethod
    def init_git_bare_if_needed(self) -> None:
        """
        If this directory is empty, runs git init --bare.
        """

    @abc.abstractmethod
    def open(self, mode: str) -> BinaryIO:
        """
        Opens this file for reading or writing in binary mode.

        :param mode: The mode, e.g. "r", "w".
        """