from dataclasses import dataclass, field
from typing import Any
from .settings import Settings


@dataclass(repr=False)
class AgentContext:
    llm: Any = field(repr=False)
    repository: Any = field(repr=False)
    budget: Any = field(repr=False)
    telemetry: Any = field(repr=False)
    settings: Settings = field(repr=False)
