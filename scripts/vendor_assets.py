"""Vendor the three frontend libraries at pinned versions (spec §3 row 4, §17 supply chain).

No runtime CDN: htmx, Alpine.js and Chart.js are downloaded once at their pinned versions into
`src/hrmosaic/web/static/vendor/` and committed. For each file the script records
`{file, version, upstream_url}` in a managed block at the end of the hand-authored
`static/vendor/LICENSES.md`; the MIT/BSD licence texts above that block are never touched.

If a pinned version has been withdrawn (HTTP 404) the script resolves the nearest published
release of the same major, prints `PINNED <name> <version>` and records the substitution with
its date in `CHANGELOG.md`, so a vendoring drift is always visible in the history.

Usage:  python scripts/vendor_assets.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "src" / "hrmosaic" / "web" / "static" / "vendor"
LICENSES = VENDOR_DIR / "LICENSES.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

BLOCK_BEGIN = "<!-- vendored-assets:begin -->"
BLOCK_END = "<!-- vendored-assets:end -->"

CDN = "https://cdn.jsdelivr.net/npm/{package}@{version}/{path}"
REGISTRY = "https://registry.npmjs.org/{package}"


@dataclass(frozen=True)
class Asset:
    name: str
    package: str
    version: str
    path: str
    filename: str


ASSETS = (
    Asset("htmx", "htmx.org", "2.0.9", "dist/htmx.min.js", "htmx.min.js"),
    Asset("alpine", "alpinejs", "3.15.2", "dist/cdn.min.js", "alpine.min.js"),
    Asset("chart.js", "chart.js", "4.5.1", "dist/chart.umd.js", "chart.umd.js"),
)


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _released_versions(package: str) -> list[tuple[int, ...]]:
    data = json.loads(_get(REGISTRY.format(package=package)))
    versions = []
    for raw in data.get("versions", {}):
        parts = raw.split(".")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            versions.append(tuple(int(part) for part in parts))
    return sorted(versions)


def _nearest_release(package: str, pinned: str) -> str:
    """The highest release at or below the pinned version in the same major, else the lowest above it."""
    wanted = tuple(int(part) for part in pinned.split("."))
    versions = _released_versions(package)
    if not versions:
        raise RuntimeError(f"no published releases found for {package}")
    same_major = [version for version in versions if version[0] == wanted[0]]
    candidates = same_major or versions
    below = [version for version in candidates if version <= wanted]
    chosen = below[-1] if below else candidates[0]
    return ".".join(str(part) for part in chosen)


def fetch(asset: Asset) -> tuple[str, str, bytes]:
    """Return `(version, upstream_url, payload)`, resolving the nearest release on a 404."""
    url = CDN.format(package=asset.package, version=asset.version, path=asset.path)
    try:
        return asset.version, url, _get(url)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    version = _nearest_release(asset.package, asset.version)
    print(f"PINNED {asset.name} {version}")
    url = CDN.format(package=asset.package, version=version, path=asset.path)
    return version, url, _get(url)


def write_licences(rows: list[tuple[str, str, str]]) -> None:
    text = LICENSES.read_text(encoding="utf-8")
    table = [
        BLOCK_BEGIN,
        "",
        "| File | Version | Upstream URL |",
        "|---|---|---|",
        *(f"| `{file}` | {version} | {url} |" for file, version, url in rows),
        "",
        BLOCK_END,
    ]
    block = "\n".join(table)
    if BLOCK_BEGIN in text and BLOCK_END in text:
        head, _, rest = text.partition(BLOCK_BEGIN)
        _, _, tail = rest.partition(BLOCK_END)
        text = f"{head}{block}{tail}"
    else:
        text = f"{text.rstrip()}\n\n{block}\n"
    LICENSES.write_text(text, encoding="utf-8")


def record_substitutions(substitutions: list[tuple[str, str, str]]) -> None:
    if not substitutions:
        return
    today = dt.date.today().isoformat()
    lines = [
        f"- {today} — `scripts/vendor_assets.py` could not fetch the pinned version of "
        f"{name} ({pinned}); vendored the nearest release {resolved} instead."
        for name, pinned, resolved in substitutions
    ]
    existing = CHANGELOG.read_text(encoding="utf-8").rstrip()
    CHANGELOG.write_text(existing + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, str]] = []
    substitutions: list[tuple[str, str, str]] = []
    for asset in ASSETS:
        version, url, payload = fetch(asset)
        (VENDOR_DIR / asset.filename).write_bytes(payload)
        rows.append((asset.filename, version, url))
        if version != asset.version:
            substitutions.append((asset.name, asset.version, version))
        print(f"vendored {asset.filename} {version} ({len(payload)} bytes)")
    write_licences(rows)
    record_substitutions(substitutions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
