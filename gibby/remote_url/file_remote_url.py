import logging
import os
import platform
import shutil
import stat
from collections.abc import Generator
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Optional

from gibby.git import Git

from .remote_url import RemoteUrl

logger = logging.getLogger()


class FileRemoteUrl(RemoteUrl):
    def __init__(self, raw_url: str) -> None:
        super().__init__(raw_url)
        if self._raw_parse_result.netloc:
            raise ValueError(
                "File URLs with a remote location are not supported. Did you mean file:/// with 3 slashes?"
            )
        self._local_path = Path(self._url_path_to_local_path(self._unquoted_path))

    @classmethod
    def _url_path_to_local_path(cls, local_path: str) -> str:
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

    def init_git_bare_if_needed(self, initial_branch: Optional[str] = None) -> None:
        if next(self._local_path.iterdir(), None) is None:
            logger.info(f"Initializing new git repo at {self._local_path}")
            Git(self._local_path).create_bare_repository(initial_branch)

    def list_children(self) -> Generator[str, None, None]:
        for child in self._local_path.iterdir():
            yield child.name

    def is_dir(self) -> bool:
        return self._local_path.is_dir()

    def is_file(self) -> bool:
        return self._local_path.is_file()

    def rmtree(self) -> None:
        if self._local_path.is_dir():

            def on_error(
                func: Callable[..., Any], path: str, excinfo: tuple[type[BaseException], BaseException, TracebackType]
            ) -> None:
                # Some files within .git are read-only. Attempt to delete them anyway by changing permissions.
                os.chmod(path, stat.S_IWUSR)
                func(path)

            shutil.rmtree(self._local_path, onerror=on_error)
        else:
            self._local_path.unlink()
