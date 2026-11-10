# Releasing xcontracts

A release is an annotated tag `vMAJOR.MINOR.PATCH` on `master`; a pre-release
is `vMAJOR.MINOR.PATCH-rc.N`. Pushing the tag runs
[`.github/workflows/release.yml`](../.github/workflows/release.yml), which checks
the release, publishes the wheel and source distribution to PyPI and attaches
them to the GitHub release. xormania decides when to release. Choose the version
with the [compatibility policy](../README.md#compatibility-policy).

## What the workflow does

| Job | Runs on | Does |
| --- | --- | --- |
| Build distributions and check release identity | tag push, manual run | builds the wheel and sdist with the locked tools (`python -m build --no-isolation`), then runs `scripts/release_identity.py` |
| Run the conformance kit from the built distributions | after build | installs the wheel and the sdist into clean environments and runs the kit against the reference fakes, without pytest |
| Publish | after both | uploads with trusted publishing: to PyPI (environment `pypi`) for a tag push, to TestPyPI (environment `testpypi`) for a manual run |
| Attach distributions to the GitHub release | tag push, after publish | creates the release with the changelog entry as notes (pre-release for `-rc.N`), or uploads to an existing one |

The identity gate fails the run unless the tag is `vX.Y.Z` or `vX.Y.Z-rc.N`;
`__version__` in `xcontracts/__init__.py` and `version` in `pyproject.toml`
equal it without the `v`; `pyproject.toml` declares `license = "Apache-2.0"`;
`CHANGELOG.md` has a `## X.Y.Z` entry with a non-empty `### Compatibility`
section; the build produced exactly one wheel and one sdist of that version, the
wheel declaring `License-Expression: Apache-2.0` and shipping `LICENSE` and
`py.typed`; and, for a tag push, the tag is annotated and on `master`. CI runs
the same gate as a dry run (no tag) on every pull request.

Only the publish job can request an OIDC token; no PyPI token is stored. Only
the GitHub release job can write repository contents.

## One-time setup (owner)

These are settings outside the repository; this document does not claim they
have been made.

1. **Accounts.** A PyPI account and a TestPyPI account, both with two-factor
   authentication.
2. **Trusted publishers.** The `xcontracts` project exists on PyPI and TestPyPI
   once the `0.0.1` name placeholder is uploaded. Then add a trusted publisher
   on each (*Your projects → xcontracts → Manage → Publishing → Add a new
   publisher → GitHub*):

   | Field | PyPI | TestPyPI |
   | --- | --- | --- |
   | Owner | `xormania` | `xormania` |
   | Repository name | `xcontracts` | `xcontracts` |
   | Workflow name | `release.yml` | `release.yml` |
   | Environment name | `pypi` | `testpypi` |

   Without the placeholder, use a *pending* publisher instead, which creates
   the project on the first upload.
3. **GitHub environments.** In *Settings → Environments*, create `pypi`
   (required reviewers; deployment tags limited to `v*.*.*`) and `testpypi`
   (required reviewers). No secrets are needed.
4. **Tag ruleset.** In *Settings → Rules → Rulesets*, restrict creating,
   updating and deleting `v*` tags to maintainers.

The gate runs inside the tagged commit's own workflow, so it catches mistakes,
not someone who controls that commit. The tag ruleset and the required
reviewers are what stop an unreviewed upload.

## Release procedure

1. Move the `Unreleased` changelog notes into `## X.Y.Z - YYYY-MM-DD` with its
   **Compatibility** section, and add a new empty `Unreleased` entry.
2. Set `__version__` and the `pyproject.toml` version to `X.Y.Z`, run
   `uv lock`, and commit both in the release pull request.
3. Optional dry run: run *Release* manually on the branch; it publishes to
   TestPyPI. TestPyPI refuses a repeated file name, so rehearse again with an
   `-rc.N` version.
4. Merge, then tag the merge commit and push the tag:

   ```sh
   git switch master && git pull --ff-only
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

5. Approve the `pypi` deployment after checking that the run's commit is the
   merged release commit.

For 0.1.0 the changelog entry exists already; set its date when tagging.
Xorchestrate depends on `xcontracts>=0.1,<0.2`; until 0.1.0 is on PyPI it
uses a uv git source, which its own release gate refuses.
