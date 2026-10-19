"""Check PORTAL_ROUTE_ALLOWLIST in a portal value file before applying (README.md section 3).

The portal has no login, and the OpenShift router admits every client when it sets no client
ACL: for an empty allowlist, and on 4.14 also for a list with leading or trailing spaces or
with any entry that is not an IPv4/IPv6 address or CIDR (router parseIPList). This check
refuses all of them, plus two stricter cases: entries must be separated by single spaces, and
no entry may admit every address (a /0 prefix). It also keeps the 61-entry limit of README.md.

Usage: python3 check_route_allowlist.py <portal-values.env>. Python 3.8 or later, standard
library only. Exit status 0 prints "allowlist ok"; 1 prints one STOP line per problem.
"""

from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path

KEY = "PORTAL_ROUTE_ALLOWLIST"
MAX_ENTRIES = 61
# Dotted decimal without leading zeros, which the router's parser (Go net.ParseIP) refuses
# and older Python versions would read as decimal.
_IPV4 = re.compile(r"(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}")
_PREFIX = re.compile(r"0|[1-9][0-9]{0,2}")


def entry_problem(entry: str) -> str | None:
    """Why one allowlist entry would break or widen the router ACL, or None when it is valid."""
    address, slash, prefix = entry.partition("/")
    if slash and not _PREFIX.fullmatch(prefix):
        return "has an invalid prefix length"
    if ":" not in address and not _IPV4.fullmatch(address):
        return "is not an IPv4 address or CIDR"
    if "%" in address:
        return "has an IPv6 zone, which the router does not accept"
    try:
        network = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return "is not a valid IPv4 or IPv6 address or CIDR"
    if network.prefixlen == 0:
        return "admits every address"
    return None


def problems(value: str) -> list[str]:
    """Every reason the allowlist value is unsafe to apply; empty when it is valid."""
    if not value.strip():
        return [f"{KEY} is empty, so the router would admit every client"]
    entries = value.split(" ")
    if len(entries) > MAX_ENTRIES:
        return [f"{KEY} has {len(entries)} entries; the router accepts at most {MAX_ENTRIES}"]
    found: list[str] = []
    if "" in entries:
        found.append(f"separate {KEY} entries by single spaces, with none before or after")
    for entry in entries:
        if entry:
            problem = entry_problem(entry)
            if problem:
                found.append(f"{entry!r} {problem}")
    return found


def read_value(path: Path) -> list[str]:
    """Every value the file assigns to the allowlist, in order."""
    prefix = KEY + "="
    return [
        line[len(prefix) :]
        for line in path.read_text("utf-8").splitlines()
        if line.startswith(prefix)
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 check_route_allowlist.py <portal-values.env>", file=sys.stderr)
        return 2
    values = read_value(Path(argv[1]))
    if not values:
        found = [f"{KEY} is missing from {argv[1]}"]
    elif len(values) > 1:
        found = [f"{KEY} is set {len(values)} times in {argv[1]}; keep one line"]
    else:
        found = problems(values[0])
    for problem in found:
        print(f"STOP: {problem}")
    if found:
        return 1
    print("allowlist ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
