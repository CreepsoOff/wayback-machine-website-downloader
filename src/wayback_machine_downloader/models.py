from __future__ import annotations

import dataclasses
import enum


class SnapshotStrategy(str, enum.Enum):
    LATEST = "latest"
    NEAREST = "nearest"
    BEFORE = "before"
    AFTER = "after"


@dataclasses.dataclass(frozen=True, slots=True)
class Capture:
    urlkey: str
    timestamp: str
    original: str
    mimetype: str
    statuscode: str
    digest: str
    length: str
    source: str = "scope"
    depth: int = 0

    @property
    def id(self) -> str:
        return f"{self.timestamp} {self.original}"

    @property
    def replay_url(self) -> str:
        return f"https://web.archive.org/web/{self.timestamp}id_/{self.original}"

    @property
    def numeric_status(self) -> int | None:
        return int(self.statuscode) if self.statuscode.isdigit() else None

    @property
    def is_redirect(self) -> bool:
        status = self.numeric_status
        return status is not None and 300 <= status < 400

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Capture":
        fields = {field.name for field in dataclasses.fields(cls)}
        return cls(**{key: value[key] for key in fields if key in value})  # type: ignore[arg-type]


@dataclasses.dataclass(slots=True)
class DownloadedCapture:
    capture: Capture
    cache_path: str
    response_headers: dict[str, str]
    response_status: int
    raw_size: int
    decoded_size: int
    digest_verified: bool | None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = dataclasses.asdict(self)
        data["capture"] = self.capture.to_dict()
        return data

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "DownloadedCapture":
        data = dict(value)
        data["capture"] = Capture.from_dict(data["capture"])  # type: ignore[arg-type]
        return cls(**data)  # type: ignore[arg-type]
