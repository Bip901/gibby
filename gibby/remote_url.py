import abc
import logging
import os
import platform
import urllib.parse
from pathlib import Path
from typing import BinaryIO, Union

from .git import Git

logger = logging.getLogger()


class RemoteUrl:
    def __init__(self, raw_url: str) -> None:
        self.raw_url = raw_url
        self._parse_result = urllib.parse.urlparse(raw_url)

    def joinpath(self, relative_path: Union[str, Path]) -> "RemoteUrl":
        new_url = urllib.parse.urljoin(self.raw_url, str(relative_path))
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
    def open(self, mode: str = "r") -> BinaryIO:
        """
        Opens a file for reading or writing, in binary mode.

        :param mode: The mode, e.g. "r", "w".
        """

    @abc.abstractmethod
    def init_git_bare_if_needed(self) -> None:
        """
        If this directory is empty, runs git init --bare.
        """


class FileRemoteUrl(RemoteUrl):
    def __init__(self, raw_url: str) -> None:
        super().__init__(raw_url)
        if self._parse_result.netloc:
            raise ValueError(
                "File URLs with a remote location are not supported. Did you mean file:/// with 3 slashes?"
            )
        self._local_path = Path(self._url_path_to_local_path(self._parse_result.path))

    @classmethod
    def _url_path_to_local_path(cls, quoted_path: str) -> str:
        local_path = urllib.parse.unquote(quoted_path)
        if (
            platform.system().casefold() == "windows"
            and len(local_path) >= 3
            and local_path[0] == "/"
            and local_path[2] == ":"
        ):
            return local_path[1:]
        return local_path

    def __str__(self) -> str:
        return str(self._local_path)

    def mkdirs(self, permissions: int = 0o777) -> None:
        missing_directories = []
        directory = self._local_path
        while not directory.exists():
            missing_directories.append(directory)
            next_directory = directory.parent
            if directory == next_directory:
                break
            directory = next_directory
        for directory in reversed(missing_directories):
            directory.mkdir(mode=permissions)

    def open(self, mode: str = "r") -> BinaryIO:
        return self._local_path.open(mode + "b")

    def init_git_bare_if_needed(self) -> None:
        if next(self._local_path.iterdir(), None) is None:
            logger.info(f"Initializing new git repo at {self._local_path}")
            Git().run(self._local_path, "init", "--bare")


KNOWN_SCHEMES: dict[str, type[RemoteUrl]] = {"file": FileRemoteUrl}


def parse(url_string: str) -> RemoteUrl:
    try:
        scheme_end_index = url_string.index(
            "://"
        )  # The // is technically optional according to the URI spec, but we need to support Windows paths that contain ':' (C:/Foo)
        scheme = url_string[:scheme_end_index]
    except ValueError:  # No explicit scheme
        canon_local_path = str(Path(url_string).absolute()).replace(os.sep, "/")
        url_string = "file:///" + urllib.parse.quote(canon_local_path)
        scheme = "file"
    if not url_string.endswith("/"):
        url_string += "/"  # Mark as a directory for proper urljoin

    if scheme in KNOWN_SCHEMES:
        return KNOWN_SCHEMES[scheme](url_string)
    else:
        raise ValueError(f"Unsupported scheme '{scheme}'.")
