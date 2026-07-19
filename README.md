# Wayback Machine Website Downloader

A small, dependency-free Python tool that reconstructs an entire archived website from the Internet Archive's Wayback Machine.

Instead of crawling links from a homepage, it queries the Wayback CDX index for every successful capture under the site's host. This also finds archived pages and assets that are orphaned, unlinked, or absent from the selected homepage.

## Features

- Inventories the complete host through the Wayback CDX API
- Follows CDX resume keys without a fixed page limit
- Downloads HTML, CSS, JavaScript, images, JSON, and other indexed files
- Selects the latest capture of every URL by default
- Can reconstruct a composite snapshot nearest a specified timestamp
- Downloads original archived responses through Wayback's `id_` replay mode
- Rewrites internal HTML and CSS references for local browsing
- Preserves query-string variants using collision-safe filenames
- Retries temporary archive errors with exponential backoff
- Resumes automatically when files already exist
- Produces machine-readable inventory and completion reports
- Uses only the Python standard library

## Requirements

- Python 3.10 or newer
- Internet access to `web.archive.org`

No packages need to be installed.

## Usage

Pass the original HTTPS website URL—not a Wayback replay URL:

```bash
python3 wayback_mirror.py https://example.com --output example-mirror
```

The default output directory is `wayback-mirror` when `--output` is omitted.

The URL argument must use HTTPS. Inputs such as the following are deliberately rejected:

```text
https://web.archive.org/web/20250101000000/https://example.com/
http://example.com/
```

### Reconstruct a point in time

By default, the downloader selects the newest successful capture for each distinct URL. To select the capture nearest a particular time instead:

```bash
python3 wayback_mirror.py https://example.com \
  --timestamp 20250101120000 \
  --output example-2025
```

Timestamps use `YYYYMMDDhhmmss` in UTC.

### Restrict the CDX date range

The optional bounds are inclusive and can contain between 1 and 14 timestamp digits:

```bash
python3 wayback_mirror.py https://example.com \
  --from 2024 \
  --to 2025 \
  --output example-archive
```

### Inventory without downloading

```bash
python3 wayback_mirror.py https://example.com \
  --inventory-only \
  --output example-inventory
```

### Include subdomains

The default scope covers only the exact host. To include its subdomains, override the CDX scope explicitly:

```bash
python3 wayback_mirror.py https://example.com \
  --scope '*.example.com/' \
  --output example-domain
```

## Options

```text
usage: wayback_mirror.py [-h] [-o OUTPUT] [--timestamp TIMESTAMP]
                         [--from FROM_TS] [--to TO_TS] [--scope SCOPE]
                         [--workers WORKERS] [--delay DELAY]
                         [--page-size PAGE_SIZE] [--inventory-only]
                         url

positional arguments:
  url                   original HTTPS site URL

options:
  -o, --output PATH     destination directory (default: wayback-mirror)
  --timestamp VALUE     14-digit point-in-time selection target
  --from VALUE          inclusive CDX timestamp lower bound
  --to VALUE            inclusive CDX timestamp upper bound
  --scope VALUE         CDX scope override
  --workers N           concurrent downloads (default: 1)
  --delay SECONDS       minimum interval between requests (default: 0.75)
  --page-size N         records requested per CDX page (default: 5000)
  --inventory-only      write the inventory without fetching captures
```

The conservative request defaults are intentional. Wayback is a shared public service and may refuse bursty replay traffic. If concurrency is increased, retain a nonzero delay.

## Output and completeness

Every run writes two audit files:

- `wayback-inventory.json` lists every selected URL, capture timestamp, replay URL, MIME type, digest, and local path.
- `wayback-report.json` compares the number of expected, downloaded, and failed URLs.

The command exits with status `1` if any capture fails. Rerun the same command to retry missing files; existing non-empty files are retained.

In this project, “complete” means every publicly accessible HTTP `200` capture returned by Wayback's CDX index for the selected scope and date range. The downloader cannot retrieve captures excluded or blocked by the Internet Archive. Third-party assets on unrelated hosts are outside the default scope; download those hosts separately if they are required.

## How it works

1. The original hostname is converted to a CDX prefix query such as `example.com/*`.
2. The tool follows sequential CDX resume keys until the server returns no continuation token.
3. Successful captures are grouped by exact original URL.
4. The latest capture, or the one nearest `--timestamp`, is selected for every URL.
5. Each resource is downloaded using `/{timestamp}id_/{original-url}`.
6. Same-site HTML and CSS references are rewritten to their mapped local files.
7. The final report records every success and failure.

## Development

Run the test suite with:

```bash
python3 -m unittest -v
```

The project intentionally avoids runtime dependencies to keep installation and auditing simple.

## License

MIT
