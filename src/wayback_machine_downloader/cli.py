from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys
from typing import Any

from . import __version__
from .config import MirrorConfig, load_config
from .mirror import Mirror
from .models import SnapshotStrategy


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Reconstruct an archived website from the Wayback Machine CDX index.")
    result.add_argument("url", nargs="?", help="original HTTPS site URL, for example https://example.com")
    result.add_argument("--config", type=pathlib.Path, help="JSON or TOML configuration file")
    result.add_argument("-o", "--output")
    result.add_argument("--timestamp", help="14-digit point-in-time target")
    result.add_argument("--strategy", choices=[item.value for item in SnapshotStrategy])
    result.add_argument("--from", dest="from_timestamp", help="inclusive CDX timestamp lower bound")
    result.add_argument("--to", dest="to_timestamp", help="inclusive CDX timestamp upper bound")
    result.add_argument("--scope-type", choices=["host", "domain", "prefix"])
    result.add_argument("--scope", help="legacy/raw CDX scope override")
    result.add_argument("--status", dest="statuses", action="append", help="status code, class (3xx), or any; repeatable")
    result.add_argument("--mime", dest="mime_types", action="append", help="included MIME regex/value; repeatable")
    result.add_argument("--exclude-mime", dest="exclude_mime_types", action="append", help="excluded MIME regex/value; repeatable")
    result.add_argument("--all-timestamps", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--external-host", dest="external_hosts", action="append", help="allowlisted external host; repeatable")
    result.add_argument("--external-depth", type=int)
    result.add_argument("--external-budget", type=int)
    result.add_argument("--discover-javascript", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--verify-digests", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--export-warc", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--workers", type=int)
    result.add_argument("--delay", type=float)
    result.add_argument("--page-size", type=int)
    result.add_argument("--inventory-only", action=argparse.BooleanOptionalAction, default=None)
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return result


def config_from_args(args: argparse.Namespace) -> MirrorConfig:
    values: dict[str, Any] = load_config(args.config) if args.config else {}
    valid_fields = {field.name for field in dataclasses.fields(MirrorConfig)}
    unknown = sorted(set(values) - valid_fields)
    if unknown:
        raise ValueError("unknown configuration keys: " + ", ".join(unknown))
    for key, value in vars(args).items():
        if key in {"config"} or value is None:
            continue
        if key in valid_fields:
            values[key] = value
    return MirrorConfig(**values).normalized()


def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    try:
        config = config_from_args(args)
        if not config.url:
            argument_parser.error("an original HTTPS URL is required (argument or config)")
        if config.timestamp:
            if len(config.timestamp) != 14 or not config.timestamp.isdigit():
                argument_parser.error("--timestamp must contain 14 digits")
        elif not config.all_timestamps and config.strategy in {SnapshotStrategy.NEAREST, SnapshotStrategy.BEFORE, SnapshotStrategy.AFTER}:
            argument_parser.error(f"--strategy {config.strategy.value} requires --timestamp")
        return Mirror(config).run()
    except (ValueError, OSError, RuntimeError) as exc:
        argument_parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
