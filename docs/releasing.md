# Releasing

Four distributions, one entrance:
**a version bump reaching `main` is the release.**

## Cutting one

```bash
cd funduq-contract && uv version --bump patch
```

Open that as a pull request, review it like any other diff, merge it. The
workflow notices which `pyproject.toml` declares a new version, publishes
that distribution, and writes the tag afterwards.

Nothing else to remember, and nothing to keep in sync: the version lives in
exactly one place a human writes, and the tag is derived from it after the
upload succeeds. **A tag existing means that version is on PyPI.**

If several move together, `funduq-contract` publishes first — the other two
declare it as a dependency, and an install resolves nothing until it exists.

## The gate is the environment

Merging publishes, and PyPI is irreversible: a filename cannot be reused, so
a wrong version is not something a later commit fixes. Give each of the three
environments a **required reviewer** and every upload stops for a human
first. That is the pause; there is no second one.

## There is no token

PyPI trusts this repository, this workflow *file*, and one environment per
project; GitHub mints a short-lived OIDC token per run. Nothing long-lived is
stored anywhere, and revoking a publisher is a click rather than a secret
rotation.

Four things are load-bearing configuration and not free to change:

| | |
|---|---|
| `hukaichun/funduq` | the repository |
| `release.yml` | the workflow **filename** |
| `pypi-funduq`, `pypi-funduq-contract`, `pypi-funduq-provider-sdk` | one environment per project |

Renaming any of them breaks publishing silently. The environments are
separate because PyPI refuses to register one
`(owner, repo, workflow, environment)` against more than one project name —
a rule worth keeping rather than working around, since one configuration able
to publish several names is one thing to compromise for all of them.

## Two designs that look better and are not

**Deriving the version from the tag** (hatch-vcs and friends) would remove
the number from `pyproject.toml` entirely, so nothing could disagree. It
fails here, and silently: it works by `git describe`, which finds the nearest
reachable tag whatever its prefix. With three interleaved tag series in one
repository, building `funduq-contract` just after a `funduq-provider-sdk`
release yields the provider-sdk's version — measured, not guessed — and PyPI
accepts it. A per-package `--match` pattern repairs it, at the price of a
misconfiguration publishing a wrong version instead of failing.

**Tagging in one workflow and publishing on the tag in another** cannot work
at all: events created with `GITHUB_TOKEN` do not start workflow runs, so the
release would simply never happen. Detection and publication are one workflow
for that reason, and no personal access token is needed anywhere.

## A name is not yours until you publish

A pending publisher does **not** reserve a project name. Until the first
upload, anyone may register it — including through a pending publisher of
their own.
