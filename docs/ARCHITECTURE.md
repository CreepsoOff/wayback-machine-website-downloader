# Architecture and V2 extension point

V1.5 keeps the default runtime dependency-free and separates the workflow into explicit phases:

1. `cdx.py` inventories the primary scope and exact external URLs with persistent continuation tokens.
2. `selection.py` applies `latest`, `nearest`, `before`, `after`, or all-timestamp selection.
3. `mirror.py` stores decoded replay payloads in a resumable content cache and verifies CDX digests.
4. `discovery.py` extracts HTML, CSS, and heuristic JavaScript URLs behind an allowlist, depth, and budget.
5. `paths.py` creates a collision-safe mapping for internal and external resources.
6. `rewrite.py` materializes locally browsable HTML and CSS only after discovery is complete.
7. `reports.py` and `warc.py` produce audit artifacts and an optional WARC 1.1 resource export.

## Browser support in V2

`discovery.DiscoveryProvider` is a small protocol. A future Playwright provider can implement it and feed observed network URLs into the same allowlist, CDX lookup, budget, download, mapping, and reporting pipeline.

The `browser` packaging extra is intentionally empty in V1.5. No Playwright code or transitive browser dependency ships in this release.
