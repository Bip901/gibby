import os
import subprocess
from pathlib import Path
from typing import Optional

GIT_DIR_ENVIRONMENT_VAR = "GIT_DIR"
GIT_DIR_DEFAULT = ".git"
GIT_EXECUTABLE_ENVIRONMENT_VAR = "GIT_EXECUTABLE"
GIT_EXECUTABLE_DEFAULT = "git"
GIT_IGNORE_FILE_NAME = ".gitignore"


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
        Returns the name of the current branch, or None if in detached head mode.
        """

        result = self("branch", "--show-current").rstrip("\n")
        if result:
            return result
        return None

    def checkout(self, branch: str) -> None:
        """
        Performs git checkout to the given branch.

        :param branch: The name of the branch to check out.
        """
        self("checkout", branch)

    def create_bare_repository(self) -> None:
        """
        Creates a new bare repository at the current working directory.
        """
        self("init", "--bare")

    def __call__(self, *args: str) -> str:
        process = subprocess.run(
            [get_git_executable(), *args], input=None, stdout=subprocess.PIPE, text=True, cwd=self.cwd, check=True
        )
        return process.stdout

    def run_with_stdin(self, stdin: bytes, *args: str) -> bytes:
        process = subprocess.run(
            [get_git_executable(), *args], input=stdin, stdout=subprocess.PIPE, text=False, cwd=self.cwd, check=True
        )
        return process.stdout
