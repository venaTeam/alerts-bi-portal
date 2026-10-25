"""The pinned design snapshot must hold exactly the bytes its manifest records."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/upstream/manifest.json"


def _pinned() -> dict[str, str]:
    hashes: dict[str, str] = json.loads(MANIFEST.read_text("utf-8"))["sha256"]
    return hashes


def test_pinned_design_hashes_match() -> None:
    for relative, expected in _pinned().items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative


def test_the_snapshot_holds_no_unpinned_file() -> None:
    present = {
        path.relative_to(ROOT).as_posix()
        for folder in ("docs/upstream", "docs/decisions")
        for path in (ROOT / folder).rglob("*")
        if path.is_file() and path != MANIFEST
    }
    assert present == set(_pinned())
