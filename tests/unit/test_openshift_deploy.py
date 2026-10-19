"""The OpenShift template, its value file and the portal's own settings stay in step.

A deploying agent fills only deploy/openshift/values.env.example, so every template parameter
must be there with the template's default, and the template must set every PORTAL_* setting.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from src.config import DEFAULT_ALLOWED_NETWORKS, DEFAULT_PORTAL_PORT, PortalSettings

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "openshift"

# The substitution syntax of `oc process`.
_STRING_PARAMETER = re.compile(r"\$\{([a-zA-Z0-9_]+?)\}")
_VALUE_PARAMETER = re.compile(r"\$\{\{([a-zA-Z0-9_]+)\}\}")
_SETTING_READ = re.compile(r"""read_(?:str|int|bool)\(\s*["']([A-Z][A-Z0-9_]*)["']""")


def _template() -> tuple[str, dict[str, dict[str, str]]]:
    text = (DEPLOY / "portal.yaml").read_text("utf-8")
    objects, separator, declared = text.partition("\nparameters:\n")
    assert separator, "portal.yaml has no parameters section"
    parameters: dict[str, dict[str, str]] = {}
    for block in ("\n" + declared).split("\n  - name: ")[1:]:
        lines = block.splitlines()
        fields = dict(line.strip().split(": ", 1) for line in lines[1:] if line.strip())
        parameters[lines[0].strip()] = fields
    return objects, parameters


def _default(fields: dict[str, str]) -> str:
    value = fields.get("value", "")
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] == '"' else value


def _values_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (DEPLOY / "values.env.example").read_text("utf-8").splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_template_declares_exactly_the_parameters_it_uses() -> None:
    objects, parameters = _template()
    used = set(_STRING_PARAMETER.findall(objects)) | set(_VALUE_PARAMETER.findall(objects))
    assert used == set(parameters)


def test_values_example_holds_every_parameter_with_the_template_default() -> None:
    _, parameters = _template()
    values = _values_example()
    assert set(values) == set(parameters)
    for key, fields in parameters.items():
        assert values[key] == _default(fields), key


def test_the_route_allowlist_is_required_and_defaults_to_the_private_ranges() -> None:
    # The portal has no login and the router admits every client when the Route's allowlist is
    # empty, so `oc process` must refuse an empty override while the example keeps the default.
    _, parameters = _template()
    allowlist = parameters["PORTAL_ROUTE_ALLOWLIST"]
    assert allowlist.get("required") == "true"
    assert _default(allowlist) == "10.0.0.0/8 172.16.0.0/12 192.168.0.0/16"


def _allowlist_checker() -> ModuleType:
    """deploy/openshift/check_route_allowlist.py, the runbook's pre-apply check."""
    path = DEPLOY / "check_route_allowlist.py"
    spec = importlib.util.spec_from_file_location("check_route_allowlist", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_runbook_runs_the_allowlist_check_before_applying() -> None:
    runbook = (DEPLOY / "README.md").read_text("utf-8")
    check = runbook.index('python3 check_route_allowlist.py "$VALUES_DIR/portal-values.env"')
    assert check < runbook.index("oc apply")


@pytest.mark.parametrize(
    "value",
    [
        # Empty, blank or padded: the router sets no client ACL.
        "",
        " ",
        "   ",
        "10.0.0.0/8 ",
        " 10.0.0.0/8",
        "10.0.0.0/8  172.16.0.0/12",
        # Not addresses at all.
        "10.0.0.0/8,172.16.0.0/12",
        "company network",
        "10.0.0.0/8 everyone",
        # Invalid IPv4 octets.
        "999.0.0.1",
        "10.0.0.256",
        "256.1.1.1/8",
        "010.0.0.1",
        "10.0.0",
        "10.0.0.0.1",
        # Invalid prefix lengths.
        "10.0.0.0/33",
        "10.0.0.0/",
        "10.0.0.0/08",
        "10.0.0.0/-1",
        "10.0.0.0/8/8",
        "fd00::/129",
        # Malformed IPv6.
        ":",
        ":::",
        "fd00::g",
        "1:2:3:4:5:6:7:8:9",
        "fd00:::1",
        "fe80::1%eth0",
        # Admits every address.
        "0.0.0.0/0",
        "::/0",
        "10.0.0.0/8 0.0.0.0/0",
        # More entries than the router takes.
        " ".join(["10.0.0.1"] * 62),
    ],
)
def test_the_allowlist_check_refuses_an_empty_or_invalid_allowlist(value: str) -> None:
    assert _allowlist_checker().problems(value)


@pytest.mark.parametrize(
    "value",
    [
        "203.0.113.7",
        "10.0.0.1/8",
        "fd00::/8 10.1.2.0/24",
        "::ffff:10.0.0.1",
        "2001:db8::1/128",
        " ".join(["10.0.0.1"] * 61),
    ],
)
def test_the_allowlist_check_accepts_a_valid_allowlist(value: str) -> None:
    assert _allowlist_checker().problems(value) == []


def test_the_allowlist_check_reads_the_value_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checker = _allowlist_checker()
    values = tmp_path / "portal-values.env"
    example = (DEPLOY / "values.env.example").read_text("utf-8")
    values.write_text(example, "utf-8")
    assert checker.main(["check", str(values)]) == 0
    assert capsys.readouterr().out == "allowlist ok\n"
    bad = example.replace(
        "PORTAL_ROUTE_ALLOWLIST=10.0.0.0/8 172.16.0.0/12 192.168.0.0/16",
        "PORTAL_ROUTE_ALLOWLIST=10.0.0.0/8 999.0.0.1 10.0.0.0/33",
    )
    values.write_text(bad, "utf-8")
    assert checker.main(["check", str(values)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "STOP: '999.0.0.1' is not a valid IPv4 or IPv6 address or CIDR",
        "STOP: '10.0.0.0/33' is not a valid IPv4 or IPv6 address or CIDR",
    ]
    for text, problem in [
        ("PORTAL_IMAGE=x\n", "is missing"),
        ("PORTAL_ROUTE_ALLOWLIST=10.0.0.0/8\nPORTAL_ROUTE_ALLOWLIST=\n", "assigned on lines 1, 2"),
        ("PORTAL_ROUTE_ALLOWLIST=\n", "is empty"),
    ]:
        values.write_bytes(text.encode("utf-8"))
        assert checker.main(["check", str(values)]) == 1
        assert problem in capsys.readouterr().out


def test_the_allowlist_check_reads_parameters_as_oc_does() -> None:
    # oc 4.14 pkg/helpers/newapp/app/env.go: keys are trimmed, `export` and `KEY: value` are
    # accepted, quotes and trailing comments are removed, CR LF is a line end, last one wins.
    text = (
        "# comment\nA=1\n  B = 2 \r\nexport C='x y'\nD: 4\nE=\"5 # kept\"\nF=6 # dropped\n\nA=7\n"
    )
    assert _allowlist_checker().oc_parameters(text) == {
        "A": "7",
        "B": "2",
        "C": "x y",
        "D": "4",
        "E": "5 # kept",
        "F": "6",
    }


VALID = "PORTAL_ROUTE_ALLOWLIST=10.0.0.0/8"


@pytest.mark.parametrize(
    "text",
    [
        # Review case: oc keeps the last, malformed value; a line-prefix check saw only the first.
        f"{VALID}\n PORTAL_ROUTE_ALLOWLIST=999.0.0.1\n",
        f"{VALID}\nexport PORTAL_ROUTE_ALLOWLIST=999.0.0.1\n",
        f"{VALID}\nPORTAL_ROUTE_ALLOWLIST: 999.0.0.1\n",
        f"{VALID}\nPORTAL_ROUTE_ALLOWLIST =999.0.0.1\n",
        f"{VALID}\n{VALID}\n",
        # One assignment in a form oc rewrites, even with a valid list.
        " PORTAL_ROUTE_ALLOWLIST=10.0.0.0/8\n",
        "export PORTAL_ROUTE_ALLOWLIST=10.0.0.0/8\n",
        "PORTAL_ROUTE_ALLOWLIST: 10.0.0.0/8\n",
        'PORTAL_ROUTE_ALLOWLIST="10.0.0.0/8"\n',
        "PORTAL_ROUTE_ALLOWLIST=10.0.0.0/8 # office\n",
        # Lines oc cannot read make it fail, so they are refused before oc runs.
        f"{VALID}\nnot an assignment\n",
        f"{VALID}\n\tPORTAL_ROUTE_ALLOWLIST=999.0.0.1\n",
    ],
)
def test_the_allowlist_check_refuses_duplicate_or_rewritten_assignments(text: str) -> None:
    assert _allowlist_checker().file_problems(text)


@pytest.mark.parametrize(
    "text",
    [
        f"{VALID}\n",
        f"{VALID}",
        f"PORTAL_IMAGE=x\r\n{VALID}\r\n",
        f"# PORTAL_ROUTE_ALLOWLIST=999.0.0.1\n{VALID}\n",
    ],
)
def test_the_allowlist_check_accepts_one_plain_assignment(text: str) -> None:
    assert _allowlist_checker().file_problems(text) == []


def test_template_sets_every_portal_setting_the_code_reads() -> None:
    objects, _ = _template()
    read = {
        name
        for source in (ROOT / "src").rglob("*.py")
        for name in _SETTING_READ.findall(source.read_text("utf-8"))
    }
    portal_settings = {name for name in read if name.startswith("PORTAL_")}
    assert portal_settings == {
        "PORTAL_HOST",
        "PORTAL_PORT",
        "PORTAL_ALLOWED_NETWORKS",
        "PORTAL_PAGE_SIZE",
    }
    for name in portal_settings:
        assert f"{{name: {name}, value: " in objects, name


def test_defaults_match_the_application_defaults() -> None:
    objects, parameters = _template()
    assert _default(parameters["PORTAL_ALLOWED_NETWORKS"]) == ",".join(DEFAULT_ALLOWED_NETWORKS)
    assert "127.0.0.0/8" in DEFAULT_ALLOWED_NETWORKS
    page_size = next(
        field.default for field in dataclasses.fields(PortalSettings) if field.name == "page_size"
    )
    assert _default(parameters["PORTAL_PAGE_SIZE"]) == str(page_size)
    assert f'{{name: PORTAL_PORT, value: "{DEFAULT_PORTAL_PORT}"}}' in objects
    assert f"containerPort: {DEFAULT_PORTAL_PORT}" in objects


def test_template_reads_only_the_sql_login_and_shared_configuration() -> None:
    objects, _ = _template()
    keys = re.findall(r'secretKeyRef: \{name: "\$\{PORTAL_SQL_SECRET\}", key: ([A-Z_]+)\}', objects)
    assert keys == ["SQL_USER", "SQL_PASSWORD"]
    assert "secretRef" not in objects
    assert re.findall(r"configMapRef: \{name: ([a-z-]+)\}", objects) == ["alerts-bi-config"]
    assert re.findall(r"^\s*image: (.+)$", objects, flags=re.MULTILINE) == ['"${PORTAL_IMAGE}"']
