import logging
import os
import shlex
import subprocess
from collections.abc import Generator, Iterable
from enum import Enum
from pathlib import Path
from typing import Optional, Union

GIT_DIR_ENVIRONMENT_VAR = "GIT_DIR"
GIT_DIR_DEFAULT = ".git"
GIT_EXECUTABLE_ENVIRONMENT_VAR = "GIT_EXECUTABLE"
GIT_EXECUTABLE_DEFAULT = "git"
GIT_IGNORE_FILE_NAME = ".gitignore"

GIT_BARE_SENTRY_FILE = "HEAD"
"""
When this file is present in a directory, it's a git bare repository.
"""


git_directory_name = os.environ.get(GIT_DIR_ENVIRONMENT_VAR, GIT_DIR_DEFAULT)
_git_executable = os.environ.get(GIT_EXECUTABLE_ENVIRONMENT_VAR, GIT_EXECUTABLE_DEFAULT)

logger = logging.getLogger()


def get_git_executable() -> str:
    global _git_executable
    if _git_executable is not None:
        return _git_executable
    _git_executable = os.environ.get(GIT_EXECUTABLE_ENVIRONMENT_VAR, GIT_EXECUTABLE_DEFAULT)
    try:
        subprocess.run([_git_executable, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception as ex:
        raise ValueError(
            f'Failed running git with "{_git_executable}". Check that git is installed on your PATH, or set the {GIT_DIR_ENVIRONMENT_VAR} environment variable manually.'
        ) from ex
    return _git_executable


class GitOngoingOperation(Enum):
    CHERRY_PICK = 1
    MERGE = 2
    REBASE = 3
    REVERT = 4

    def get_sentry_rev(self) -> str:
        if self == GitOngoingOperation.CHERRY_PICK:
            return "CHERRY_PICK_HEAD"
        elif self == GitOngoingOperation.MERGE:
            return "MERGE_HEAD"
        elif self == GitOngoingOperation.REBASE:
            return "REBASE_HEAD"
        elif self == GitOngoingOperation.REVERT:
            return "REVERT_HEAD"
        else:
            raise ValueError("Unknown operation")


class Git:
    def __init__(self, cwd: Path) -> None:
        """
        :param cwd: git working directory.
        """
        self.cwd = cwd

    def get_current_branch(self) -> Optional[str]:
        """
        Returns the short name of the current branch, or None if in detached head mode.
        """

        result = self("branch", "--show-current", is_read_only=True).decode().rstrip("\n")
        if result:
            return result
        return None

    def is_orphan(self, branch_name: str) -> bool:
        """
        Returns whether the given branch is an orphan (has no commits).

        :param branch_name: The branch name, either short-form or long-form (refs/heads/...)
        """

        if not branch_name.startswith("refs/heads/"):
            branch_name = "refs/heads/" + branch_name  # Disambiguate from commit hash
        try:
            self("rev-parse", branch_name, stderr=subprocess.DEVNULL, is_read_only=True)
            return False
        except subprocess.CalledProcessError:
            return True

    def get_current_commit_hash(self) -> str:
        """
        Returns the full hash of the current commit (HEAD).
        """

        return self("rev-parse", "HEAD", is_read_only=True).decode().rstrip("\n")

    def is_ongoing_operation(self, operation: GitOngoingOperation) -> bool:
        if (
            operation == GitOngoingOperation.REBASE
        ):  # rebase requires special treatment because it may leave REBASE_HEAD after the rebase
            return (self.cwd / git_directory_name / "rebase-merge").is_dir() or (
                self.cwd / git_directory_name / "rebase-apply"
            ).is_dir()
        try:
            self("rev-parse", "--verify", operation.get_sentry_rev(), stderr=subprocess.DEVNULL, is_read_only=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_local_branches(self) -> list[str]:
        """
        Lists the full branch names of all local branches (e.g. refs/heads/main).
        """
        stdout = self("branch", "--list", "--format", "%(refname)", is_read_only=True)
        return stdout.decode().strip("\n").splitlines()

    def create_bare_repository(self, initial_branch: Optional[str] = None) -> None:
        """
        Creates a new bare repository at the current working directory.
        """
        if initial_branch:
            self("init", "--bare", "--initial-branch", initial_branch)
        else:
            self("init", "--bare")

    def get_remotes(self) -> list[str]:
        stdout = self("remote", is_read_only=True)
        return stdout.decode().splitlines()

    def get_remote_branches(self, remote_url: str) -> list[str]:
        """
        Connects to the given remote URL and returns its full branch names (e.g. refs/heads/main).
        """
        stdout = self("ls-remote", "--heads", "--", remote_url, is_read_only=True)
        return [line.split()[1] for line in stdout.decode().strip("\n").splitlines()]

    def get_remote_tags(self, remote_url: str) -> list[str]:
        """
        Connects to the given remote URL and returns its full tag names (e.g. refs/tags/my-tag).
        """
        stdout = self("ls-remote", "--tags", "--", remote_url, is_read_only=True)
        return [line.split()[1] for line in stdout.decode().strip("\n").splitlines()]

    def does_remote_exist(self, remote_url: str) -> bool:
        """
        Connects to the given remote URL and tests if it responds properly.
        """
        try:
            self("ls-remote", "--heads", "--", remote_url, stderr=subprocess.DEVNULL, is_read_only=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_commit_message(self, commit_or_branch: str) -> str:
        """
        Returns the full commit message of the given commit.

        :param commit: The commit hash or branch name.
        """

        stdout = self("show", "-s", "--format=%B", commit_or_branch, is_read_only=True)
        return stdout.decode()

    def check_attr(self, attribute: str, paths: Iterable[Path]) -> Generator[tuple[Path, str], None, None]:
        """Yields pairs of (path, attribute value) for paths that have the given attribute set."""

        def encode_path(path: Path) -> bytes:
            result = str(path.relative_to(self.cwd))
            if path.is_dir() and not result.endswith("/"):
                result += "/"
            return result.encode()

        stdin = b"\0".join(map(encode_path, paths))
        stdout = self("check-attr", "--stdin", "-z", attribute, stdin=stdin, is_read_only=True)
        i = 0
        while i < len(stdout):
            try:
                next_separator = stdout.index(b"\0", i)
            except ValueError:
                break
            path = stdout[i:next_separator]
            i = stdout.index(b"\0", next_separator) + 1  # Skip the "tag" field
            i = stdout.index(b"\0", i) + 1
            try:
                next_separator = stdout.index(b"\0", i)
            except ValueError:
                next_separator = len(stdout)
            value = stdout[i:next_separator].decode()
            i = next_separator + 1
            if value != "unspecified":
                yield (self.cwd / path.decode(), value)

    @staticmethod
    def quote_pathspec(path: Union[str, Path]) -> str:
        result = str(path)
        if result.startswith(":") or ("*" in result) or ("?" in result):
            result = ":(literal)" + result
        return result

    def __call__(
        self, *args: str, stdin: Optional[bytes] = None, stderr: Optional[int] = None, is_read_only: bool = False
    ) -> bytes:
        """
        Invokes git with the given arguments:

        :param args: The command-line arguments to pass to git.
        :param stdin: Optionally, the bytes to pass to the standard input of git.
        :param stderr: A "_FILE" such as subprocess.DEVNULL to redirect git's stderr to. If set to None, outputs to the stderr of the current process.
        :param is_read_only: Indicates that this call does not change the state of the repo.
        """

        commandline = [get_git_executable(), *args]
        if not is_read_only:
            logger.debug("Executing: " + " ".join(shlex.quote(x) for x in commandline))
        process = subprocess.run(
            commandline,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=False,
            cwd=self.cwd,
            check=True,
        )
        return process.stdout
