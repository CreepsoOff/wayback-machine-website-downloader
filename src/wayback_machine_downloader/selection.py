from __future__ import annotations

import datetime as dt
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable

from .models import Capture, SnapshotStrategy


def clean_url(url: str) -> str:
    return urllib.parse.urldefrag(url)[0]


def timestamp_value(timestamp: str) -> dt.datetime:
    return dt.datetime.strptime(timestamp, "%Y%m%d%H%M%S")


def select_group(group: list[Capture], strategy: SnapshotStrategy, target: str | None) -> Capture | None:
    if strategy == SnapshotStrategy.LATEST:
        return max(group, key=lambda item: item.timestamp)
    if not target:
        raise ValueError(f"snapshot strategy {strategy.value} requires --timestamp")
    target_value = timestamp_value(target)
    if strategy == SnapshotStrategy.NEAREST:
        return min(group, key=lambda item: (abs((timestamp_value(item.timestamp) - target_value).total_seconds()), item.timestamp))
    if strategy == SnapshotStrategy.BEFORE:
        candidates = [item for item in group if item.timestamp <= target]
        return max(candidates, key=lambda item: item.timestamp) if candidates else None
    if strategy == SnapshotStrategy.AFTER:
        candidates = [item for item in group if item.timestamp >= target]
        return min(candidates, key=lambda item: item.timestamp) if candidates else None
    raise ValueError(f"unknown strategy: {strategy}")


def select_captures(
    captures: Iterable[Capture],
    *,
    strategy: SnapshotStrategy,
    target: str | None,
    all_timestamps: bool = False,
) -> tuple[list[Capture], list[str]]:
    deduplicated: dict[tuple[str, str], Capture] = {}
    for capture in captures:
        original = clean_url(capture.original)
        normalized = Capture(
            capture.urlkey,
            capture.timestamp,
            original,
            capture.mimetype,
            capture.statuscode,
            capture.digest,
            capture.length,
            capture.source,
            capture.depth,
        )
        deduplicated[(original, capture.timestamp)] = normalized
    if all_timestamps:
        return sorted(deduplicated.values(), key=lambda item: (item.timestamp, item.original)), []

    grouped: dict[str, list[Capture]] = defaultdict(list)
    for capture in deduplicated.values():
        grouped[capture.original].append(capture)
    selected: list[Capture] = []
    missing: list[str] = []
    for url, group in grouped.items():
        capture = select_group(group, strategy, target)
        if capture:
            selected.append(capture)
        else:
            missing.append(url)
    return sorted(selected, key=lambda item: item.original), sorted(missing)
