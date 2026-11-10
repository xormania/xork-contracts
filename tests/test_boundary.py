"""The package depends on the standard library only, never on a host, and the kit does not import pytest."""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import xcontracts
from xcontracts import factories, ports
from xcontracts.testing import factory

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "xcontracts"


def imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module


def test_every_import_is_the_standard_library_or_the_package_itself():
    foreign = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for module in imported_modules(path):
            top = module.split(".")[0]
            if top != "xcontracts" and top not in sys.stdlib_module_names:
                foreign.setdefault(str(path.relative_to(ROOT)), []).append(module)
    assert foreign == {}, "xcontracts must stay stdlib-only and must not import its hosts (such as xorchestrate)"


def test_the_distribution_declares_no_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == [] and "optional-dependencies" not in project
    assert project["license"] == "Apache-2.0" and project["license-files"] == ["LICENSE", "NOTICE"]
    assert project["authors"] == [{"name": "xormania"}]
    assert (PACKAGE / "py.typed").is_file()


def test_importing_the_kit_does_not_import_pytest():
    script = "import sys, xcontracts.testing.state_store, xcontracts.testing.operator, xcontracts.testing.fakes; " \
             "print('pytest' in sys.modules)"
    completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60,
                               check=True)
    assert completed.stdout.strip() == "False"


def test_every_public_name_resolves_and_the_version_matches_the_project():
    assert all(hasattr(xcontracts, name) for name in xcontracts.__all__)
    assert xcontracts.__version__ == tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


# Ports a third party does not supply through a selectable kind.
UNSELECTED = {"Transaction", "ResumableSessionDriver", "ApplicationToolSessionDriver", "ApplicationToolCallback",
              "Clock", "CompanionRecords",
              # Provisional: passes host internals, so third parties cannot implement it yet.
              "TelemetrySink"}


def test_every_port_is_selectable_through_a_kind_or_deliberately_not():
    protocols = {name for name, value in vars(ports).items()
                 if isinstance(value, type) and getattr(value, "_is_protocol", False) and value.__module__ == ports.__name__}
    selectable = {kind.port.__name__ for kind in factories.KINDS.values()}
    assert protocols == selectable | UNSELECTED and not selectable & UNSELECTED
    assert all(name in xcontracts.__all__ for name in protocols)


def test_port_members_follow_inheritance():
    assert factory.port_members(ports.ResumableSessionDriver) == {"start", "send", "poll", "stop", "close", "resume"}
    assert factory.port_members(ports.Companion) == {"location", "validate_location", "exists", "initialize", "records",
                                                     "remote", "revision"}


def test_reference_splitting_follows_the_first_separator():
    assert factories.split_reference("package.module:Name") == ("package.module", "Name")
    assert factories.split_reference("a:b:c") == ("a", "b:c")
    for invalid in ("", "module", ":Name", "module:", None):
        try:
            factories.split_reference(invalid)
        except ValueError:
            continue
        raise AssertionError(f"{invalid!r} was accepted")


def test_the_readme_adapter_example_is_a_guardrail():
    text = (ROOT / "README.md").read_text()
    source = text.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(compile(source, "README.md", "exec"), namespace)  # noqa: S102 - the repository's own documentation
    guardrail = namespace["DenyActions"]({"actions": ["start_session"]})
    assert isinstance(guardrail, ports.Guardrail) and factory.missing_members(guardrail, ports.Guardrail) == []
    assert guardrail.evaluate("start_session", {}).allowed is False
    assert guardrail.evaluate("list_work", {}).allowed is True
