from __future__ import annotations

import dataclasses
import json


@dataclasses.dataclass
class State:
    current_branch: str | None = None

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), indent=2)

    @classmethod
    def from_json(cls, json_string: str) -> State:
        json_dict = json.loads(json_string)
        return cls(**json_dict)
