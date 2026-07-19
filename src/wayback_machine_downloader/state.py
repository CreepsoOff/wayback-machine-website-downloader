from __future__ import annotations

import json
import pathlib
import threading
from typing import Any


class StateStore:
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {"version": 1, "queries": {}, "downloads": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass

    def query(self, fingerprint: str) -> dict[str, Any]:
        return self.data.setdefault("queries", {}).setdefault(fingerprint, {"captures": [], "resume_key": None, "complete": False})

    def save_query(self, fingerprint: str, *, captures: list[dict[str, object]], resume_key: str | None, complete: bool) -> None:
        with self._lock:
            self.data.setdefault("queries", {})[fingerprint] = {"captures": captures, "resume_key": resume_key, "complete": complete}
            self._write()

    def download(self, capture_id: str) -> dict[str, Any] | None:
        return self.data.setdefault("downloads", {}).get(capture_id)

    def save_download(self, capture_id: str, value: dict[str, Any]) -> None:
        with self._lock:
            self.data.setdefault("downloads", {})[capture_id] = value
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)
