"""A standalone clone must contain the exact local archives Poetry will accept."""

import hashlib
import tomllib
from pathlib import Path


def test_vendored_archive_bytes_match_poetry_lock() -> None:
    root = Path(__file__).resolve().parents[2]
    lock = tomllib.loads((root / "poetry.lock").read_text(encoding="utf-8"))
    local_packages = [
        package for package in lock["package"] if package.get("source", {}).get("type") == "file"
    ]
    assert local_packages, "The independent portal must lock its vendored shared archive"
    for package in local_packages:
        archive = root / package["source"]["url"]
        allowed = {
            artifact["hash"] for artifact in package["files"] if artifact["file"] == archive.name
        }
        actual = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
        assert actual in allowed, f"{archive.name}: lock does not accept committed bytes ({actual})"
