"""The OpenShift template, its value file and the portal's own settings stay in step.

A deploying agent fills only deploy/openshift/values.env.example, so every template parameter
must be there with the template's default, and the template must set every PORTAL_* setting.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

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
        expected = "" if fields.get("required") == "true" else _default(fields)
        assert values[key] == expected, key


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
