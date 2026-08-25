# Releasing

Four distributions, published one at a time from
[`.github/workflows/release.yml`](https://github.com/hukaichun/funduq/blob/main/.github/workflows/release.yml).

## There is no token

PyPI trusts this repository, this workflow *file*, and one named environment
per project; GitHub mints a short-lived OIDC token per run. Nothing
long-lived is stored anywhere, and revoking a publisher is a click rather
than a secret rotation.

Three things are therefore part of the configuration and not free to change:

| | |
|---|---|
| `hukaichun/funduq` | the repository |
| `release.yml` | the workflow **filename** |
| `pypi-funduq`, `pypi-funduq-contract`, `pypi-funduq-provider-sdk` | one environment per project |

Renaming any of them breaks publishing silently, and the error arrives at the
worst moment. The environments are separate because PyPI refuses to register
one `(owner, repo, workflow, environment)` against more than one project
name — a rule worth keeping rather than working around, since one
configuration able to publish several names is one thing to compromise for
all of them.

## Cutting a release

1. **Decide whether the contract moved.** If the surface changed, the suite
   has already refused to go green without a revision bump and a
   [changelog](contract-changelog.md) entry, so this is a question you have
   answered rather than one to remember.
2. **Set the version** in that distribution's `pyproject.toml`.
3. **Tag it**, and the tag names the distribution:

   ```
   funduq-contract-v0.1.0
   funduq-v0.1.0
   funduq-provider-sdk-v0.1.0
   ```

   The workflow refuses a tag whose version disagrees with the package's own,
   because PyPI does not allow reusing a filename: publishing 0.1.0 under a
   `v0.2.0` tag is not something a later commit can fix.

4. **`funduq-contract` goes first** when several go out together. The other
   two declare it as a dependency, and an install resolves nothing until it
   exists.

## Rehearsing on TestPyPI

`workflow_dispatch` takes a target. TestPyPI is a **separate site**, not a
mode of this one, so it needs its own three pending publishers registered at
test.pypi.org — same repository, same workflow filename, same environment
names.

Worth doing once before the first real publish, because it is the only thing
that shows what someone else gets from `pip install`. Building a wheel
locally proves it builds; it does not prove it installs, resolves its
dependencies, or imports on a machine that has none of this checked out.

## A name is not yours until you publish

A pending publisher does **not** reserve a project name. Until the first
upload, anyone may register it — including through a pending publisher of
their own. That is the whole reason not to sit on a configured-but-unpublished
state longer than necessary.
