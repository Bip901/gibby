from pathlib import Path

from pydantic import BaseModel

from .git import GIT_IGNORE_FILE_NAME

class Config(BaseModel):
    pass


GIBBY_DIRECTORY_NAME = ".gibby"
CONFIG_FILE_NAME = "config.json"


def get(directory: Path) -> Config:
    gibby_directory = directory / GIBBY_DIRECTORY_NAME
    if not gibby_directory.exists():
        return Config()
    config_file = gibby_directory / CONFIG_FILE_NAME
    if not config_file.exists():
        return Config()
    json_text = config_file.read_text()
    return Config.model_validate_json(json_text)


def set(directory: Path, config: Config) -> None:
    gibby_directory = directory / GIBBY_DIRECTORY_NAME
    if not gibby_directory.exists():
        gibby_directory.mkdir()
        (gibby_directory / GIT_IGNORE_FILE_NAME).write_text("*")
    config_file = gibby_directory / CONFIG_FILE_NAME
    config_file.write_text(config.model_dump_json(indent=4))
