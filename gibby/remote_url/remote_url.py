from __future__ import annotations

import abc
import urllib.parse
from collections.abc import Generator
from pathlib import Path, PurePosixPath


class RemoteUrl:
    def __init__(self, raw_url: str) -> None:
        """Creates a new RemoteUrl.

        :param raw_url: The quoted URL, e.g. file:///D%3A/Users
        """

        self.raw_url = raw_url
        self._raw_parse_result = urllib.parse.urlparse(raw_url)
        self._unquoted_path = urllib.parse.unquote(self._raw_parse_result.path)

    def joinpath(self, relative_path: str | Path) -> RemoteUrl:
        raw_url = self.raw_url
        if not raw_url.endswith("/"):
            raw_url += "/"  # Mark as a directory for proper urljoin
        new_url = urllib.parse.urljoin(raw_url, str(relative_path))
        return type(self)(new_url)

    def relative_to(self, other: RemoteUrl) -> str:
        """
        Return the relative path to another path.
        If the operation is not possible (because this is not a subpath of the other path), raise ValueError.
        """

        if self._raw_parse_result.scheme != other._raw_parse_result.scheme:
            raise ValueError(
                f"Scheme '{self._raw_parse_result.scheme}' can't be matched with '{other._raw_parse_result.scheme}'"
            )
        if self._raw_parse_result.netloc != other._raw_parse_result.netloc:
            raise ValueError(
                f"Netloc '{self._raw_parse_result.netloc}' can't be matched with '{other._raw_parse_result.netloc}'"
            )

        # URLs use the Posix directory separator '/' instead of the Windows '\'
        new_path = str(PurePosixPath(self._unquoted_path).relative_to(PurePosixPath(other._unquoted_path)))

        new_parse_result = list(self._raw_parse_result)
        new_parse_result[2] = urllib.parse.quote(new_path)
        return urllib.parse.urlunparse(*new_parse_result)

    def __str__(self) -> str:
        return self.raw_url

    @abc.abstractmethod
    def mkdirs(self, permissions: int = 0o777) -> None:
        """
        Creates this directory and all parent directories as necessary.

        :param permissions: The filesystem permissions to apply to all created directories. May be combined with this processe's umask.
        """

    @abc.abstractmethod
    def init_git_bare_if_needed(self, initial_branch: str | None = None) -> None:
        """
        If this directory is empty, runs git init --bare.

        :param initial_branch: The name of the initial branch to check out, or None to use the default value.
        """

    @abc.abstractmethod
    def list_children(self) -> Generator[str, None, None]:
        """
        Yields just the names of immediate children of this directory. Does not yield "." or "..".

        See also: iterdir

        :raises NotADirectoryError:
        """

    def iterdir(self) -> Generator[RemoteUrl, None, None]:
        """
        Yields the full URLs of the immediate children of this directory. Does not yield "." or "..".

        See also: list_children

        :raises NotADirectoryError:
        """
        for child in self.list_children():
            yield self.joinpath(child)

    @abc.abstractmethod
    def is_dir(self) -> bool:
        """
        Returns whether this URL exists and points to a directory.
        """
