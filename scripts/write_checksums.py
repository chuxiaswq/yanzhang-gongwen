#!/usr/bin/env python3
"""Write deterministic SHA-256 checksums for release archives."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    directory = args.directory.resolve()
    archives = sorted(
        (*directory.glob("*.whl"), *directory.glob("*.tar.gz"), *directory.glob("*.zip")),
        key=lambda p: p.name,
    )
    if not archives:
        parser.error(f"no wheel, sdist or connector archive found in {directory}")
    output = directory / "SHA256SUMS"
    output.write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in archives), encoding="utf-8"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
