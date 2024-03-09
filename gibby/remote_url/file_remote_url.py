import logging
import platform
import urllib.parse
from pathlib import Path

from ..git import Git
from .remote_url import RemoteUrl

logger = logging.getLogger()


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

    def init_git_bare_if_needed(self) -> None:
        if next(self._local_path.iterdir(), None) is None:
            logger.info(f"Initializing new git repo at {self._local_path}")
            Git(self._local_path).create_bare_repository()
