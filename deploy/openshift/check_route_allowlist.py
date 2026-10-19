"""Check PORTAL_ROUTE_ALLOWLIST in a portal value file before applying (README.md sections 3, 5).

The portal has no login, and the OpenShift router admits every client when it sets no client
ACL: for an empty allowlist, and on 4.14 also for a list with leading or trailing spaces or
with any entry that is not an IPv4/IPv6 address or CIDR (router parseIPList). This check
refuses all of them, plus two stricter cases: entries must be separated by single spaces, and
no entry may admit every address (a /0 prefix). It also keeps the 61-entry limit of README.md.
Dotted IPv4, alone or at the end of an IPv6 literal, is checked by its own strict rule rather
than by `ipaddress`, whose leading-zero handling changed in Python 3.8.12 and 3.9.5.

The value checked is the one `oc process --param-file` uses. oc 4.14 reads the file with its
own copy of godotenv (pkg/helpers/newapp/app/env.go): it trims keys, accepts `export KEY=`,
`KEY: value`, quotes and trailing comments, and the last assignment of a key wins. This module
ports that parser, refuses a file oc could not read, and also refuses any assignment of the
allowlist other than one plain `PORTAL_ROUTE_ALLOWLIST=<list>` line, so what is reviewed is
exactly what is rendered.

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
# Kubernetes IsEnvVarName, which oc applies to every key it reads from a parameter file.
_ENV_VAR_NAME = re.compile(r"[-._a-zA-Z][-._a-zA-Z0-9]*")
_ESCAPE = re.compile(r"\\.")


def entry_problem(entry: str) -> str | None:
    """Why one allowlist entry would break or widen the router ACL, or None when it is valid."""
    address, slash, prefix = entry.partition("/")
    if slash and not _PREFIX.fullmatch(prefix):
        return "has an invalid prefix length"
    if ":" not in address and not _IPV4.fullmatch(address):
        return "is not an IPv4 address or CIDR"
    # An IPv6 literal may end in dotted IPv4 (::ffff:10.0.0.1). Python 3.8.0-3.8.11 accepts
    # leading zeros there; the router refuses them, so the tail gets the same strict rule.
    if ":" in address and "." in address and not _IPV4.fullmatch(address.rsplit(":", 1)[1]):
        return "ends in an IPv4 part that is not a plain dotted address"
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


# --- oc 4.14 parameter-file parsing (pkg/helpers/newapp/app/env.go, from godotenv) ---


def _oc_lines(text: str) -> list[str]:
    """Lines as bufio.ScanLines yields them: split on LF, one trailing CR dropped."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _oc_ignored(line: str) -> bool:
    trimmed = line.strip(" \n\t")
    return not trimmed or trimmed.startswith("#")


def _oc_value(value: str) -> str:
    value = value.strip(" ")
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]

        def unescape(match: re.Match[str]) -> str:
            character = match.group(0)[1]
            return {"n": "\n", "r": "\r"}.get(character, character)

        value = _ESCAPE.sub(unescape, value)
    return value


def _oc_parse_line(line: str) -> tuple[str, str]:
    if "#" in line:
        keep: list[str] = []
        quotes_open = False
        for segment in line.split("#"):
            if segment.count('"') == 1 or segment.count("'") == 1:
                if quotes_open:
                    quotes_open = False
                    keep.append(segment)
                else:
                    quotes_open = True
            if not keep or quotes_open:
                keep.append(segment)
        line = "#".join(keep)
    equals, colon = line.find("="), line.find(":")
    separator = ":" if colon != -1 and (colon < equals or equals == -1) else "="
    parts = line.split(separator, 1)
    if len(parts) != 2:
        raise ValueError("oc cannot separate the key from the value")
    key = parts[0]
    if key.startswith("export"):
        key = key[len("export") :]
    return key.strip(" "), _oc_value(parts[1])


def oc_assignments(text: str) -> list[tuple[int, str, str, str]]:
    """(line number, raw line, key, value) for every assignment oc reads, in file order."""
    found: list[tuple[int, str, str, str]] = []
    for number, line in enumerate(_oc_lines(text), start=1):
        if _oc_ignored(line):
            continue
        try:
            key, value = _oc_parse_line(line)
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from None
        if not _ENV_VAR_NAME.fullmatch(key):
            raise ValueError(f"line {number}: oc refuses the key {key!r}")
        found.append((number, line, key, value))
    return found


def oc_parameters(text: str) -> dict[str, str]:
    """The parameter values `oc process --param-file` takes from this text: the last one wins."""
    return {key: value for _, _, key, value in oc_assignments(text)}


def file_problems(text: str) -> list[str]:
    """Every reason this value file must not be applied, judged on what oc would render."""
    try:
        assignments = oc_assignments(text)
    except ValueError as exc:
        return [f"oc cannot read the value file ({exc}); fix that line"]
    assigned = [(number, line, value) for number, line, key, value in assignments if key == KEY]
    if not assigned:
        return [f"{KEY} is missing; copy its line from values.env.example"]
    if len(assigned) > 1:
        lines = ", ".join(str(number) for number, _, _ in assigned)
        return [f"{KEY} is assigned on lines {lines}; oc uses the last one. Keep one line"]
    number, line, value = assigned[0]
    if line != f"{KEY}={value}":
        return [
            f"line {number} sets {KEY} in a form oc rewrites (spaces, export, a colon, quotes "
            f"or a comment); write it as {KEY}=<list> with nothing else on the line"
        ]
    return problems(oc_parameters(text)[KEY])


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 check_route_allowlist.py <portal-values.env>", file=sys.stderr)
        return 2
    # Bytes as oc reads them: no newline translation.
    found = file_problems(Path(argv[1]).read_bytes().decode("utf-8"))
    for problem in found:
        print(f"STOP: {problem}")
    if found:
        return 1
    print("allowlist ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
