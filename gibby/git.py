import os
import subprocess
from pathlib import Path
from typing import Any, ClassVar, Optional, Union

GIT_DIR_ENVIRONMENT_VAR = "GIT_DIR"
GIT_DIR_DEFAULT = ".git"
GIT_EXECUTABLE_ENVIRONMENT_VAR = "GIT_EXECUTABLE"
GIT_EXECUTABLE_DEFAULT = "git"
GIT_IGNORE_FILE_NAME = ".gitignore"


class Singleton(type):
    _instance: ClassVar[Optional[Any]] = None

    def __call__(cls, *args, **kwargs) -> Any:
        if cls._instance is None:
            cls._instance = super().__call__(*args, **kwargs)
        return cls._instance


class Git(metaclass=Singleton):
    _instance: ClassVar[Optional["Git"]] = None

    def __init__(self) -> None:
        self._git_executable: Optional[str] = None
        self.git_directory_name = os.environ.get(GIT_DIR_ENVIRONMENT_VAR, GIT_DIR_DEFAULT)

    @property
    def git_executable(self) -> str:
        if self._git_executable is not None:
            return self._git_executable
        self._git_executable = os.environ.get(GIT_EXECUTABLE_ENVIRONMENT_VAR, GIT_EXECUTABLE_DEFAULT)
        try:
            subprocess.run(
                [self._git_executable, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
        except Exception as ex:
            raise ValueError(
                f'Failed running git with "{self._git_executable}". Check that git is installed on your PATH, or set the {GIT_DIR_ENVIRONMENT_VAR} environment variable manually.'
            ) from ex
        return self._git_executable

    def run(self, cwd: Union[Path, str], *args: str) -> str:
        process = subprocess.run([self.git_executable, *args], stdout=subprocess.PIPE, text=True, cwd=cwd, check=True)
        return process.stdout
