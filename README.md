# Wayback Machine Website Downloader

A dependency-free, CDX-first website reconstruction tool for the Internet Archive's Wayback Machine.

V1.5 inventories archived URLs before downloading them, reconstructs coherent snapshots, discovers controlled external resources, verifies content, resumes interrupted work, and produces auditable reports. The default Python runtime has **zero third-party dependencies**.

## Why CDX-first?

Link crawlers only see resources reachable from downloaded pages. This tool first queries the Wayback CDX index for the complete selected host, domain, or path prefix. It therefore sees archived orphan pages, generated assets, JSON endpoints, and files that are not linked by the homepage.

## Features

- Unlimited CDX resume-key pagination with persistent continuation state
- `host`, `domain`, and `prefix` scopes, plus a raw legacy `--scope` override
- Snapshot strategies: `latest`, `nearest`, `before`, and `after`
- Complete capture history with `--all-timestamps`
- Repeatable status and MIME inclusion/exclusion filters
- `warc/revisit` resolution through CDX
- Archived redirect reconstruction as local redirect pages
- SHA-1/Base32 CDX digest verification against raw and decoded replay payloads
- Exact-URL external asset discovery controlled by host allowlist, depth, and URL budget
- HTML, CSS, and heuristic JavaScript discovery (`fetch`, dynamic `import`, `require`, Axios, `new URL`, asset literals)
- Local HTML/CSS link rewriting after discovery completes
- Collision-safe paths for query strings, protocols, timestamps, and external hosts
- Persistent per-capture download state and raw-body cache
- Optional WARC 1.1 resource export
- JSON URL mapping, inventory, completion report, missing-resource report, and XML sitemap
- JSON and TOML configuration
- PyPI-ready package and console command
- Optional Docker image
- No Playwright or real JavaScript execution in V1.5

## Requirements

- Python 3.11 or newer
- Internet access to `web.archive.org`

## Installation

### Run from a checkout

```bash
python3 wayback_mirror.py https://example.com --output example-mirror
```

### Install the console command

```bash
python3 -m pip install .
wayback-machine-downloader https://example.com --output example-mirror
```

The published package metadata is ready for PyPI, but availability on PyPI depends on a separate release/upload.

### Docker

```bash
docker build -t wayback-machine-downloader .
docker run --rm -v "$PWD/output:/output" wayback-machine-downloader \
  https://example.com --output /output/example-mirror
```

## URL input

Pass the original HTTPS site URL:

```bash
wayback-machine-downloader https://example.com
```

Wayback replay URLs and plain HTTP inputs are deliberately rejected:

```text
https://web.archive.org/web/20250101000000/https://example.com/
http://example.com/
```

## Snapshot selection

The default `latest` strategy selects the newest matching capture independently for every URL:

```bash
wayback-machine-downloader https://example.com --strategy latest
```

Point-in-time strategies require a 14-digit UTC timestamp:

```bash
wayback-machine-downloader https://example.com \
  --timestamp 20250101120000 \
  --strategy nearest
```

Available strategies:

| Strategy | Selection |
|---|---|
| `latest` | Newest capture for each URL |
| `nearest` | Capture closest to the target, in either direction |
| `before` | Newest capture at or before the target |
| `after` | Oldest capture at or after the target |

For backward compatibility, supplying `--timestamp` without `--strategy` automatically uses `nearest`.

Download every matching historical capture into `snapshots/<timestamp>/...`:

```bash
wayback-machine-downloader https://example.com --all-timestamps
```

## Scopes and filters

```bash
# Exact host
wayback-machine-downloader https://example.com --scope-type host

# Host and subdomains
wayback-machine-downloader https://example.com --scope-type domain

# Only the path prefix from the input URL
wayback-machine-downloader https://example.com/docs/ --scope-type prefix

# Successful pages and redirects, excluding video
wayback-machine-downloader https://example.com \
  --status 200 --status 3xx \
  --mime 'text/*' --exclude-mime 'video/*'
```

Use `--status any` to retain every indexed status. CDX timestamp bounds are inclusive:

```bash
wayback-machine-downloader https://example.com --from 2024 --to 2025
```

## Controlled external assets

External crawling is disabled unless hosts are explicitly allowed. Only URLs actually discovered in archived HTML, CSS, or JavaScript are queried; the downloader never inventories an entire third-party CDN.

```bash
wayback-machine-downloader https://example.com \
  --external-host cdn.example.com \
  --external-host fonts.example.com \
  --external-depth 2 \
  --external-budget 200
```

- **Allowlist:** exact hostnames only
- **Depth:** maximum discovery generations after the primary scope
- **Budget:** maximum distinct external URLs queried
- **Missing report:** disallowed, unavailable, depth-limited, and budget-limited discoveries are recorded

JavaScript discovery is static and heuristic. Disable it with `--no-discover-javascript`.

## Integrity, resumption, and WARC

Digest verification is enabled by default. Disable it only when diagnosing an unusual replay:

```bash
wayback-machine-downloader https://example.com --no-verify-digests
```

The output contains `.wayback-state.json` and `.wayback-cache/`. Rerunning the same command reuses completed CDX pages and downloaded captures while retrying incomplete work. Do not remove these until the mirror is finalized.

Create an optional WARC 1.1 resource export from successfully downloaded payloads:

```bash
wayback-machine-downloader https://example.com --export-warc
```

The generated `archive.warc` is a new resource WARC containing the recovered payloads and source metadata. It is not the Internet Archive's original internal WARC file.

## Configuration files

Both JSON and TOML are supported. CLI options override file values.

```bash
wayback-machine-downloader --config example-config.toml
```

Example TOML:

```toml
[wayback]
url = "https://example.com"
output = "example-mirror"
timestamp = "20250101120000"
strategy = "nearest"
scope_type = "host"
statuses = ["200", "3xx"]
external_hosts = ["cdn.example.com"]
external_depth = 2
external_budget = 100
verify_digests = true
```

See [`example-config.toml`](example-config.toml) for the complete sample.

## Audit artifacts

| File | Purpose |
|---|---|
| `wayback-inventory.json` | Configuration and every selected CDX capture |
| `wayback-report.json` | Expected/downloaded/failed counts and digest results |
| `url-map.json` | Capture ID to local path mapping |
| `missing-resources.json` | Unavailable, disallowed, depth-limited, or budget-limited discoveries |
| `sitemap.xml` | Archived HTML URLs and local alternate paths |
| `.wayback-state.json` | Persistent CDX and per-download resume state |
| `.wayback-cache/` | Decoded replay payload cache |
| `archive.warc` | Optional WARC export |

The process exits nonzero when a download or digest verification fails. “Complete” means every publicly accessible capture returned by the chosen CDX scope and filters; a downloader cannot recover material that the Internet Archive never captured or no longer exposes.

## Important options

```text
--strategy {latest,nearest,before,after}
--timestamp YYYYMMDDhhmmss
--all-timestamps
--scope-type {host,domain,prefix}
--status CODE|CLASS|any
--mime TYPE
--exclude-mime TYPE
--external-host HOST
--external-depth N
--external-budget N
--[no-]discover-javascript
--[no-]verify-digests
--export-warc
--config FILE.json|FILE.toml
--inventory-only
```

Run `wayback-machine-downloader --help` for the full CLI reference.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
python3 -m build
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for module boundaries and the V2 browser extension point.

## V2 browser mode

V1.5 does not install or invoke Playwright. `DiscoveryProvider` and the reserved `browser` packaging extra provide a clean boundary for a future optional browser implementation. The zero-dependency core will remain the default.

## License

MIT
