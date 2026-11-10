"""Release identity gate: the tag, ``__version__``, ``pyproject.toml``, changelog and distributions agree.

A release is an annotated tag ``vMAJOR.MINOR.PATCH`` (optionally ``-rc.N``) on
``master`` whose commit sets ``xcontracts.__version__`` and the
``pyproject.toml`` version to the tag without the ``v``. ``CHANGELOG.md`` has a
``## X.Y.Z`` entry with a non-empty ``### Compatibility`` section. Built
distributions, when given, are exactly one wheel and one sdist carrying that
version. The wheel declares ``License-Expression: Apache-2.0`` and ships
``LICENSE``, ``NOTICE`` and ``py.typed``; the sdist ships ``LICENSE`` and
``NOTICE`` and, by choice (``MANIFEST.in``), no ``tests/`` or ``scripts/``. Without ``--tag`` (a dry run) the expected tag is ``v`` + ``__version__``.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

PACKAGE = "xcontracts"
LICENSE = "Apache-2.0"
TAG = re.compile(r"v(?P<version>(?P<release>\d+\.\d+\.\d+)(?:-rc\.(?P<rc>\d+))?)")
ENTRY = re.compile(r"##\s+\[?v?(?P<version>[^\]\s]+)\]?(?:\s.*)?")


def normalized(version):
    """PEP 440 form used in distribution filenames: ``1.2.3-rc.4`` becomes ``1.2.3rc4``."""
    match = TAG.fullmatch("v" + version)
    return match["release"] + ("rc" + match["rc"] if match["rc"] is not None else "")


def package_version(root):
    """``__version__`` read from source without importing the package."""
    tree = ast.parse((Path(root) / PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            return node.value.value
    return None


def section(entry, heading):
    """The non-empty content of ``### heading`` in a changelog entry, or ``None``."""
    content = None
    for line in entry.splitlines():
        if line.startswith("### "):
            if content is not None:
                break
            if line[4:].strip().lower() == heading.lower():
                content = []
        elif content is not None:
            content.append(line)
    text = "\n".join(content or []).strip()
    return text or None


def changelog_entry(text, version):
    """The body of the ``## version`` entry, or ``None``."""
    body = None
    for line in text.splitlines():
        if line.startswith("## ") or line == "##":
            if body is not None:
                break
            match = ENTRY.fullmatch(line.rstrip())
            if match and match["version"] == version:
                body = []
        elif body is not None:
            body.append(line)
    return None if body is None else "\n".join(body).strip("\n")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=60)


def _check_distributions(directory, match, errors):
    files = sorted(path.name for path in directory.iterdir() if path.is_file()) if directory.is_dir() else []
    wheels = [name for name in files if name.endswith(".whl")]
    sdists = [name for name in files if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(files) != 2:
        errors.append(f"Expected exactly one wheel and one sdist in {directory}, found {files}")
        return files
    if match:
        stem = f"{PACKAGE}-{normalized(match['version'])}"
        if not wheels[0].startswith(stem + "-") or sdists[0] != stem + ".tar.gz":
            errors.append(f"Distributions {files} do not carry {stem}")
    with zipfile.ZipFile(directory / wheels[0]) as archive:
        names = archive.namelist()
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        text = archive.read(metadata[0]).decode("utf-8") if len(metadata) == 1 else ""
        if f"License-Expression: {LICENSE}" not in text.splitlines():
            errors.append(f"Wheel metadata does not declare License-Expression: {LICENSE}")
        for required in ("LICENSE", "NOTICE"):
            if not any(name.endswith(f".dist-info/licenses/{required}") for name in names):
                errors.append(f"Wheel does not ship {required}")
        if f"{PACKAGE}/py.typed" not in names:
            errors.append("Wheel does not ship py.typed")
    with tarfile.open(directory / sdists[0]) as archive:
        members = [name.split("/", 1)[1] for name in archive.getnames() if "/" in name]
    for required in ("LICENSE", "NOTICE"):
        if required not in members:
            errors.append(f"Sdist does not ship {required}")
    excluded = sorted({name.split("/", 1)[0] for name in members if name.split("/", 1)[0] in {"tests", "scripts"}})
    if excluded:
        errors.append(f"Sdist ships {excluded}; MANIFEST.in excludes them because their tests need the repository")
    return files


def check(root, *, tag=None, distributions=None, annotated=False, ancestor_of=None):
    """Return ``(report, errors)``; an empty error list means the identity agrees."""
    root, errors = Path(root), []
    version = package_version(root)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {})
    expected_tag = tag if tag is not None else (f"v{version}" if version else None)
    report = {"schema_version": 1, "tag": expected_tag, "tag_given": tag is not None, "version": version,
              "pyproject": {"name": project.get("name"), "version": project.get("version"),
                            "license": project.get("license")}}
    match = TAG.fullmatch(expected_tag or "")
    if match is None:
        errors.append(f"Tag {expected_tag!r} is not vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N")
    if version is None:
        errors.append(f"{PACKAGE}/__init__.py does not assign a string __version__")
    if match and version != match["version"]:
        errors.append(f"__version__ {version!r} does not match tag {expected_tag!r}")
    if match and project.get("version") != match["version"]:
        errors.append(f"pyproject.toml version {project.get('version')!r} does not match tag {expected_tag!r}")
    if project.get("name") != PACKAGE:
        errors.append(f"pyproject.toml name {project.get('name')!r} is not {PACKAGE!r}")
    if project.get("license") != LICENSE:
        errors.append(f"pyproject.toml license {project.get('license')!r} is not {LICENSE!r}")
    changelog = root / "CHANGELOG.md"
    entry = changelog_entry(changelog.read_text(encoding="utf-8"), match["version"]) if match and changelog.is_file() else None
    report["changelog"] = {"entry": entry is not None, "compatibility": bool(entry and section(entry, "Compatibility"))}
    if match and entry is None:
        errors.append(f"CHANGELOG.md has no '## {match['version']}' entry")
    elif match and not section(entry, "Compatibility"):
        errors.append(f"CHANGELOG.md entry {match['version']} has no non-empty '### Compatibility' section")
    report["notes"] = entry
    if distributions is not None:
        report["distributions"] = _check_distributions(Path(distributions), match, errors)
    if annotated and match:
        kind = _git(root, "cat-file", "-t", f"refs/tags/{expected_tag}").stdout.strip()
        if kind != "tag":
            errors.append(f"Tag {expected_tag} is not an annotated tag (found {kind or 'nothing'})")
    if ancestor_of is not None and match:
        contained = _git(root, "merge-base", "--is-ancestor", f"refs/tags/{expected_tag}^{{commit}}", ancestor_of)
        if contained.returncode != 0:
            errors.append(f"Tag {expected_tag} is not contained in {ancestor_of}")
    return report, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--tag", help="Release tag; omitted for a dry run, which expects v + __version__")
    parser.add_argument("--dist", type=Path, help="Directory holding the built wheel and sdist")
    parser.add_argument("--annotated", action="store_true", help="Require the tag to be an annotated git tag")
    parser.add_argument("--ancestor-of", metavar="REF", help="Require the tagged commit to be contained in REF")
    parser.add_argument("--notes-output", type=Path, help="Write the changelog entry here")
    parser.add_argument("--github-output", type=Path, help="Append tag/version/prerelease outputs here")
    args = parser.parse_args(argv)
    report, errors = check(args.root, tag=args.tag, distributions=args.dist, annotated=args.annotated,
                           ancestor_of=args.ancestor_of)
    report["status"], report["errors"] = ("failed" if errors else "passed"), errors
    print(json.dumps(report, indent=2))
    if errors:
        return 1
    if args.notes_output:
        args.notes_output.write_text(report["notes"] + "\n", encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"tag={report['tag']}\nversion={report['version']}\n"
                         f"distribution_version={normalized(report['version'])}\n"
                         f"prerelease={str('-rc.' in report['tag']).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
