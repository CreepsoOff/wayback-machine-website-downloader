# Changelog

## 1.5.0 - 2026-07-19

### Added

- Modular zero-dependency package and console entry point
- Snapshot strategies and all-timestamp archives
- Host, domain, prefix, status, and MIME filtering
- Persistent CDX continuation and per-download resume state
- Revisit resolution, redirect reconstruction, and digest verification
- Allowlisted external assets with depth and budget controls
- Static JavaScript URL discovery
- WARC export, sitemap, URL map, and missing-resource reports
- JSON/TOML configuration, Dockerfile, and V2 discovery provider boundary

### Changed

- Link rewriting now occurs after resource discovery.
- `--timestamp` continues to imply nearest-capture selection.

## 1.0.0 - 2026-07-19

- Initial CDX-first downloader.
