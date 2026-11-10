"""The release identity gate and the release workflow's shape."""

import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import release_identity

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/release_identity.py"
WORKFLOWS = ROOT / ".github/workflows"
ENTRY = "## {version} - 2026-11-10\n\n### Added\n\n- Ports.\n\n### Compatibility\n\n- Additive.\n"


def project(root, *, init="1.2.3", declared="1.2.3", license="Apache-2.0", changelog=None):
    (root / "xcontracts").mkdir(parents=True)
    (root / "xcontracts/__init__.py").write_text(f'__version__ = "{init}"\n')
    (root / "pyproject.toml").write_text(f'[project]\nname = "xcontracts"\nversion = "{declared}"\nlicense = "{license}"\n')
    (root / "CHANGELOG.md").write_text(changelog if changelog is not None else
                                       "# Changelog\n\n## Unreleased\n\n" + ENTRY.format(version="1.2.3"))
    return root


def wheel(directory, version="1.2.3", *, metadata="License-Expression: Apache-2.0\n", license=True, notice=True,
          typed=True, sdist=("LICENSE", "NOTICE", "PKG-INFO", "xcontracts/__init__.py")):
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(directory / f"xcontracts-{version}-py3-none-any.whl", "w") as archive:
        archive.writestr(f"xcontracts-{version}.dist-info/METADATA", "Name: xcontracts\n" + metadata)
        if license:
            archive.writestr(f"xcontracts-{version}.dist-info/licenses/LICENSE", "Apache")
        if notice:
            archive.writestr(f"xcontracts-{version}.dist-info/licenses/NOTICE", "xormania")
        if typed:
            archive.writestr("xcontracts/py.typed", "")
    with tarfile.open(directory / f"xcontracts-{version}.tar.gz", "w:gz") as archive:
        for name in sdist:
            data = b"content"
            info = tarfile.TarInfo(f"xcontracts-{version}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return directory


def test_an_agreeing_release_passes_and_writes_notes_and_outputs(tmp_path):
    root = project(tmp_path / "candidate")
    notes, outputs = tmp_path / "notes.md", tmp_path / "outputs"
    completed = subprocess.run([sys.executable, "-I", str(GATE), "--root", str(root), "--tag", "v1.2.3",
                                "--dist", str(wheel(tmp_path / "dist")), "--notes-output", str(notes),
                                "--github-output", str(outputs)], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout)["status"] == "passed"
    assert notes.read_text().startswith("### Added")
    assert outputs.read_text() == "tag=v1.2.3\nversion=1.2.3\ndistribution_version=1.2.3\nprerelease=false\n"


@pytest.mark.parametrize(("keywords", "tag", "message"), [
    ({"init": "1.2.4"}, "v1.2.3", "__version__ '1.2.4' does not match tag 'v1.2.3'"),
    ({"declared": "1.2.4"}, "v1.2.3", "pyproject.toml version '1.2.4' does not match tag 'v1.2.3'"),
    ({}, "1.2.3", "Tag '1.2.3' is not vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N"),
    ({"license": "MIT"}, "v1.2.3", "pyproject.toml license 'MIT' is not 'Apache-2.0'"),
    ({"changelog": "# Changelog\n"}, "v1.2.3", "CHANGELOG.md has no '## 1.2.3' entry"),
    ({"changelog": "## 1.2.3\n\n### Compatibility\n\n## 1.2.2\n"}, "v1.2.3",
     "CHANGELOG.md entry 1.2.3 has no non-empty '### Compatibility' section"),
])
def test_disagreements_are_refused(tmp_path, keywords, tag, message):
    assert message in release_identity.check(project(tmp_path, **keywords), tag=tag)[1]


@pytest.mark.parametrize(("keywords", "message"), [
    ({"metadata": "License: Apache\n"}, "Wheel metadata does not declare License-Expression: Apache-2.0"),
    ({"license": False}, "Wheel does not ship LICENSE"),
    ({"typed": False}, "Wheel does not ship py.typed"),
    ({"notice": False}, "Wheel does not ship NOTICE"),
    ({"sdist": ("LICENSE", "PKG-INFO")}, "Sdist does not ship NOTICE"),
    ({"sdist": ("NOTICE", "PKG-INFO")}, "Sdist does not ship LICENSE"),
    ({"sdist": ("LICENSE", "NOTICE", "tests/test_x.py")}, "Sdist ships ['tests']"),
    ({"version": "1.2.4"}, "do not carry xcontracts-1.2.3"),
])
def test_distributions_must_carry_the_version_license_and_types(tmp_path, keywords, message):
    problems = release_identity.check(project(tmp_path), tag="v1.2.3", distributions=wheel(tmp_path / "d", **keywords))[1]
    assert any(message in problem for problem in problems), problems


def test_release_candidates_use_their_entry_and_pep440_names(tmp_path):
    root = project(tmp_path, init="1.3.0-rc.1", declared="1.3.0-rc.1",
                   changelog="## 1.3.0-rc.1\n\n### Compatibility\n\n- None.\n")
    assert release_identity.check(root, tag="v1.3.0-rc.1", distributions=wheel(tmp_path / "d", "1.3.0rc1"))[1] == []


def test_the_repository_dry_run_agrees():
    report, problems = release_identity.check(ROOT)
    assert problems == [], problems
    assert report["tag"] == "v" + report["version"]


def workflow(name):
    return json.loads((WORKFLOWS / name).read_text())


def steps(document):
    return [step for job in document["jobs"].values() for step in job.get("steps", [])]


def test_every_action_is_pinned_to_a_full_commit():
    for name in ("ci.yml", "release.yml"):
        for step in steps(workflow(name)):
            if "uses" in step:
                reference = step["uses"].split("@", 1)[1]
                assert len(reference) == 40 and int(reference, 16) >= 0, step["uses"]


def test_release_publishes_only_after_identity_and_installed_checks_with_trusted_publishing():
    document = workflow("release.yml")
    assert document["on"] == {"push": {"tags": ["v*.*.*"]}, "workflow_dispatch": {}}
    assert document["permissions"] == {}
    jobs = document["jobs"]
    assert jobs["publish"]["needs"] == ["build", "check"]
    assert jobs["publish"]["permissions"] == {"id-token": "write"}
    assert jobs["publish"]["environment"]["name"] == "${{ github.event_name == 'push' && 'pypi' || 'testpypi' }}"
    assert all(job["permissions"] in ({"contents": "read"}, {"id-token": "write"}, {"contents": "write"})
               for job in jobs.values())
    assert jobs["github-release"]["if"] == "${{ github.event_name == 'push' }}"
    assert any("release_identity.py" in step.get("run", "") and "--annotated" in step.get("run", "")
               for step in jobs["build"]["steps"])


def test_the_built_distributions_pass_the_gate(tmp_path):
    """The real build honors MANIFEST.in and ships the license files."""
    completed = subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--outdir", str(tmp_path), str(ROOT)],
                               capture_output=True, text=True, timeout=300)
    if completed.returncode != 0 and "No module named build" in completed.stderr:
        pytest.skip("the build package is not installed")
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert release_identity.check(ROOT, distributions=tmp_path)[1] == []
