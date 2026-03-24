"""ctx — Context Assembly Tool for LLMs."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

__all__ = [
    "AssemblyResult",
    "RepoStrategy",
    "SourceResult",
    "SourceType",
    "__version__",
]

__version__ = "0.1.0"


class SourceType(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    REPO = "repo"
    URL = "url"
    STDIN = "stdin"


class RepoStrategy(str, Enum):
    """Strategy for handling repository/directory sources."""

    FULL = "full"
    MAP = "map"
    TREE = "tree"
    AUTO = "auto"


class SourceResult(BaseModel):
    """Result of loading a single source."""

    path: str
    source_type: SourceType
    content: str = ""
    tokens: int = 0
    name: str | None = None
    metadata: dict = Field(default_factory=dict)
    error: str | None = None


class AssemblyResult(BaseModel):
    """Complete result of assembling all sources."""

    output: str
    sources: list[SourceResult]
    total_tokens: int = 0
    budget_tokens: int | None = None
    over_budget: bool = False
