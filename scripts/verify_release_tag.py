#!/usr/bin/env python3
"""Verify that a preview Git tag maps to the PEP 440 project version."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

_PATTERN = re.compile(r"^v(?P<base>\d+\.\d+\.\d+)-preview\.(?P<number>[1-9]\d*)$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    args = parser.parse_args()
    match = _PATTERN.fullmatch(args.tag)
    if match is None:
        parser.error("tag must match vX.Y.Z-preview.N")
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    expected = f"{match.group('base')}b{match.group('number')}"
    if project["version"] != expected:
        parser.error(f"tag maps to {expected}, pyproject declares {project['version']}")
    print(f"{args.tag} -> {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
