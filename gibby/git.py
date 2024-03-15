import os
import subprocess
from pathlib import Path
from typing import Optional

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

        result = self("branch", "--show-current").decode().rstrip("\n")
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
            self("rev-parse", branch_name, stderr=subprocess.DEVNULL)
            return False
        except subprocess.CalledProcessError:
            return True

    def get_current_commit_hash(self) -> str:
        """
        Returns the full hash of the current commit (HEAD).
        """

        return self("rev-parse", "HEAD").decode().rstrip("\n")

    def is_ongoing_cherry_pick(self) -> bool:
        try:
            self("rev-parse", "--verify", "CHERRY_PICK_HEAD", stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def is_ongoing_merge(self) -> bool:
        try:
            self("rev-parse", "--verify", "MERGE_HEAD", stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def is_ongoing_rebase(self) -> bool:
        try:
            self("rev-parse", "--verify", "REBASE_HEAD", stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def is_ongoing_revert(self) -> bool:
        try:
            self("rev-parse", "--verify", "REVERT_HEAD", stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_local_branches(self) -> list[str]:
        """
        Lists the full branch names of all local branches (e.g. refs/heads/main).
        """
        stdout = self("branch", "--list", "--format", "%(refname)")
        return stdout.decode().strip("\n").splitlines()

    def create_bare_repository(self, initial_branch: Optional[str] = None) -> None:
        """
        Creates a new bare repository at the current working directory.
        """
        if initial_branch:
            self("init", "--bare", "--initial-branch", initial_branch)
        else:
            self("init", "--bare")

    def get_remote_branches(self, remote_url: str) -> list[str]:
        """
        Connects to the given remote URL and returns its full branch names (e.g. refs/heads/main).
        """
        stdout = self("ls-remote", "--heads", "--", remote_url)
        return [line.split()[1] for line in stdout.decode().strip("\n").splitlines()]

    def does_remote_exist(self, remote_url: str) -> bool:
        """
        Connects to the given remote URL and tests if it responds properly.
        """
        try:
            self("ls-remote", "--heads", "--", remote_url, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_commit_message(self, commit_or_branch: str) -> str:
        """
        Returns the full commit message of the given commit.

        :param commit: The commit hash or branch name.
        """

        stdout = self("show", "-s", "--format=%B", commit_or_branch)
        return stdout.decode()

    def __call__(self, *args: str, stdin: Optional[bytes] = None, stderr: Optional[int] = None) -> bytes:
        """
        Invokes git with the given arguments:

        :param args: The command-line arguments to pass to git.
        :param stdin: Optionally, the bytes to pass to the standard input of git.
        :param stderr: A "_FILE" such as subprocess.DEVNULL to redirect git's stderr to. If set to None, outputs to the stderr of the current process.
        """

        process = subprocess.run(
            [get_git_executable(), *args],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=False,
            cwd=self.cwd,
            check=True,
        )
        return process.stdout
