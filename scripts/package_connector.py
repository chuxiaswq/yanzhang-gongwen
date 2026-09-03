#!/usr/bin/env python3
"""Build a deterministic WorkBuddy connector archive from reviewed source files."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "integrations" / "workbuddy-gongwen"
MEMBERS = (
    "connector-meta.json",
    "icon.svg",
    "mcp.json",
    "skills/gongwen/SKILL.md",
    "token-schema.json",
)
ARCHIVE_ROOT = "yanzhang-workbuddy-connector"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    metadata = json.loads((SOURCE / "connector-meta.json").read_text(encoding="utf-8"))
    version = str(metadata["version"])
    output_dir = args.directory.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"yanzhang-workbuddy-connector-{version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in MEMBERS:
            info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{relative}", date_time=(2026, 9, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (SOURCE / relative).read_bytes())
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
