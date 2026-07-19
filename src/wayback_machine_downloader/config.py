from __future__ import annotations

import dataclasses
import json
import pathlib
import tomllib
from typing import Any

from .models import SnapshotStrategy


@dataclasses.dataclass(slots=True)
class MirrorConfig:
    url: str = ""
    output: str = "wayback-mirror"
    timestamp: str | None = None
    strategy: SnapshotStrategy = SnapshotStrategy.LATEST
    from_timestamp: str | None = None
    to_timestamp: str | None = None
    scope_type: str = "host"
    scope: str | None = None
    statuses: list[str] = dataclasses.field(default_factory=lambda: ["200", "3xx"])
    mime_types: list[str] = dataclasses.field(default_factory=list)
    exclude_mime_types: list[str] = dataclasses.field(default_factory=list)
    all_timestamps: bool = False
    external_hosts: list[str] = dataclasses.field(default_factory=list)
    external_depth: int = 0
    external_budget: int = 0
    discover_javascript: bool = True
    verify_digests: bool = True
    export_warc: bool = False
    workers: int = 1
    delay: float = 0.75
    page_size: int = 5000
    inventory_only: bool = False

    def normalized(self) -> "MirrorConfig":
        self.strategy = SnapshotStrategy(self.strategy)
        self.external_hosts = sorted({host.lower().strip(".") for host in self.external_hosts if host})
        self.statuses = [str(value).lower() for value in self.statuses]
        self.mime_types = [value.lower() for value in self.mime_types]
        self.exclude_mime_types = [value.lower() for value in self.exclude_mime_types]
        self.workers = max(1, self.workers)
        self.delay = max(0.0, self.delay)
        self.page_size = max(1, self.page_size)
        self.external_depth = max(0, self.external_depth)
        self.external_budget = max(0, self.external_budget)
        if self.timestamp and self.strategy == SnapshotStrategy.LATEST:
            self.strategy = SnapshotStrategy.NEAREST
        return self

    def to_public_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["strategy"] = self.strategy.value
        return data


def load_config(path: pathlib.Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix.lower() in {".toml", ".tml"}:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        value = value.get("wayback", value)
    else:
        raise ValueError("configuration must be a .json or .toml file")
    if not isinstance(value, dict):
        raise ValueError("configuration root must be an object/table")
    return value
