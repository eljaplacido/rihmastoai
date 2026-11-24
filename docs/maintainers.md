# Maintainers: releases and the two-way sync

The maintainers develop Rihmasto in a development repository of their own and publish it here as
scrubbed snapshots. Contributions arrive here as pull requests. This page is the maintainer's
procedure for both directions. Contributors need none of it:
[CONTRIBUTING.md](../CONTRIBUTING.md#how-changes-reach-main) says how a change reaches `main`.

## How the two repositories relate

- **The public `main` is protected.** It changes only through pull requests. Each one needs the four
  CI jobs and the **DCO sign-off** check to pass and a code owner's review, and is squash-merged;
  its branch is deleted after the merge. [The repository's settings](#the-repositorys-settings) say
  how GitHub is set up for this.
- **A snapshot** of a revision of the development repository is made by
  [tools/release_export.py](../tools/release_export.py). It leaves out what
  [release/exclude.txt](../release/exclude.txt) names, in any case (the build history, the original
  brief, earlier design pages) and refuses a snapshot that holds a denylisted word, a secret-like
  string, a file over 5 MB or a link to a left-out file.
- **An export** is a pull request that carries a snapshot. [tools/release_sync.py](../tools/release_sync.py)
  commits the snapshot on a branch `sync/<short sha>` made from the public `main`, titled "Sync from
  the development repository at `<short sha>`", with the trailer `Rihmasto-Export: <full sha>` at the
  end of its message and of the pull request's description.
- **A contribution** is any other commit on the public `main`. A public commit counts as an export
  only when it names a revision (by the trailer or by the sync title), the development repository
  holds that revision, its tree is that revision's snapshot, and the revision comes after the one
  the export before it carried. So a contributor cannot write or copy the trailer to skip the
  import ([tools/release_state.py](../tools/release_state.py) reads the histories).
- **An import** brings a merged contribution into the development repository as a commit of its
  own: its author and its merged message kept, the trailer `Rihmasto-Import: <public sha>` added.
  It is the three-way merge of the contribution's change, so a change that is here already is
  recorded, never applied twice ([tools/release_import.py](../tools/release_import.py)).
- **An export is refused while a contribution waits for import,** or when the revision exported
  lacks an import recorded since the last export, so an export never reverts a contribution.

## What you need

- The development repository, with the denylist `.release-denylist` at its root: the names that must
  never ship, one a line. It is never tracked and never exported.
- A clone of the public repository kept for releases, for example `../rihmasto-public`, whose
  `origin` is the public repository. The sync fetches it, adds a branch to it and pushes that
  branch; it never touches its work tree.
- git 2.40 or later, and the GitHub CLI (`gh`) signed in to GitHub, for `export --pr`.

Every command below runs from the top of the development repository. Each exits 0 when it is done,
1 when it refuses (and has changed nothing), and 2 when it cannot run.

## The repository's settings

The owner sets these once on GitHub. The sync and the checks rely on them.

- **A ruleset for `main`** (Settings, Rules, Rulesets; target: the default branch):
  - restrict deletions, and block force pushes;
  - require a pull request before merging: one approval, a review from Code Owners, stale approvals
    dismissed when new commits are pushed, and squash as the only allowed merge method;
  - require status checks to pass, with branches up to date before merging (a sync pull request is
    then never merged after `main` moved). The required checks, by the names GitHub shows:
    `ubuntu-latest, Python 3.11`, `ubuntu-latest, Python 3.12`, `windows-latest, Python 3.11`,
    `windows-latest, Python 3.12` (from [ci.yml](../.github/workflows/ci.yml)) and `DCO sign-off`
    (from [dco.yml](../.github/workflows/dco.yml));
  - the bypass list: the Repository admin role, for pull requests only. GitHub never lets the
    author of a pull request approve it, so while the owner is the only code owner, the owner's own
    pull requests (the sync ones included) can merge only through this bypass. Merge such a pull
    request only once the five checks have passed, and never push to `main` directly. When a second
    maintainer joins, add them to [CODEOWNERS](../.github/CODEOWNERS) and take the bypass off.
- **Pull requests** (Settings, General): allow squash merging only (merge commits and rebase
  merging off), with the default commit message **Default message**. For a pull request of one
  commit GitHub then proposes that commit's message, so a sync pull request keeps its
  `Rihmasto-Export:` trailer and a one-commit contribution its `Signed-off-by:` line. For several
  commits it proposes the pull request's title and the commits' messages: check that it ends with
  the contributor's `Signed-off-by:` line before you merge. Turn on **Automatically delete head
  branches**.
- **Discussions** on (Settings, General, Features), for questions.
- **Private vulnerability reporting** on (in the repository's security settings), so reports reach
  <https://github.com/eljaplacido/rihmastoai/security/advisories/new> as [SECURITY.md](../SECURITY.md) says.
- **Actions** (Settings, Actions, General): workflows on pull requests from forks wait for a
  maintainer's approval, at the strictest level GitHub offers, and the workflow permissions are
  read-only.
- **Labels:** `good first issue`, for the issues [CONTRIBUTING.md](../CONTRIBUTING.md) points
  newcomers to.

## Once: record the earlier snapshots

The public commits made before `release_sync` carry no export trailer, so the sync reads them as
contributions, though their content is already in the development repository. Record them once.

1. **Make sure `HEAD` holds every one of them.** Merge the branch the latest snapshot was made from
   first. A snapshot recorded but not held would be deleted from the public repository by the first
   export.
2. **List them.**

   ```bash
   python tools/release_sync.py status --public ../rihmasto-public
   ```

   It lists them and prints the command that records them: an empty commit with one
   `Rihmasto-Import:` trailer for each. When `HEAD`'s snapshot lacks a file the public `main` has,
   it says so under **Careful**: go back to step 1.
3. **Check, then record.** Check that every commit it lists is one of the maintainers' own
   snapshots, then run that command. Never record a real contribution that way: import it.

The first export after the record refuses to delete a file the public `main` has, and lists them.
When the deletions are meant (files removed here since the last snapshot), export with
`--allow-deletions`, and read the first sync pull request's diff for anything deleted unexpectedly.

## Every release

1. **See what waits.**

   ```bash
   python tools/release_sync.py status --public ../rihmasto-public
   ```

   It fetches the public repository and names the last export and the contributions merged after
   it that are not imported yet, oldest first. A contribution that names a revision as exported
   but is no export of it gets a line saying why.
2. **Bring the contributions in.**

   ```bash
   python tools/release_sync.py import --public ../rihmasto-public
   ```

   Each becomes a commit here, on the current branch, with its author and merged message. The
   import checks every contribution before it changes anything, and refuses them all when one
   cannot come in (see [When the sync refuses](#when-the-sync-refuses)). `--through <public sha>`
   imports the waiting contributions up to that one only. A contribution that changes
   `release/exclude.txt`, a release tool (`tools/release_*.py`) or a `.gitignore` comes in only
   after you have read its change and named it with `--reviewed <public sha>`.

   The import says, for each contribution, whether its merged message carries its author's
   `Signed-off-by:` line. When it does not (a squash message edited at the merge), the pull
   request's DCO check is the record of the sign-off: link the pull request in the changelog entry.
   A change that is here already, such as a sync pull request merged after `main` moved, is
   recorded with no change.
3. **Run the checks** on what came in, as [CONTRIBUTING.md](../CONTRIBUTING.md#run-the-checks)
   lists them, and fix anything in the development repository.
4. **Update [CHANGELOG.md](../CHANGELOG.md).** Add what changed under *Unreleased*. For a release
   with a version, move those entries under a new heading with the version and the date, and change
   the version in `pyproject.toml` and the table in [SECURITY.md](../SECURITY.md).
5. **Check the snapshot.**

   ```bash
   python tools/release_export.py --check
   ```

   A refusal names each file and line. Fix them here; the snapshot is never edited by hand.
6. **Export.**

   ```bash
   python tools/release_sync.py export --public ../rihmasto-public --pr
   ```

   It refuses while a contribution waits, scans the snapshot of `HEAD`, commits it on
   `sync/<short sha>`, pushes the branch and opens the pull request with `gh`. Without `--pr` it
   prints the commands to push the branch and open the pull request yourself. `--rev` exports an
   older revision, only when it holds the last export and every import recorded since.
7. **Merge the sync pull request** when the four CI jobs and the DCO check pass. Review the diff:
   it is everything the development repository changed since the last export. Squash-merge it with
   the message GitHub proposes under **Default message**: the export commit's message, which ends
   with the `Rihmasto-Export:` trailer. While you are the only code owner, it merges through the
   bypass (see [the settings](#the-repositorys-settings)).
8. **Confirm.** `status` now names the new export and says that nothing waits for import.
9. **Publish a version** (only for a release with a version, step 4). Once the sync pull request
   that carries the new version has merged, tag that commit on the public `main` and push the tag:

   ```bash
   git -C ../rihmasto-public pull --ff-only
   git -C ../rihmasto-public tag -s v1.2.0 -m "Rihmasto 1.2.0"     # -a if you do not sign tags
   git -C ../rihmasto-public push origin v1.2.0
   ```

   The tag starts [.github/workflows/release.yml](../.github/workflows/release.yml). It runs the
   suite and the contract again, then [tools/release_build.py](../tools/release_build.py) builds
   the source archives (`.tar.gz`, `.zip`), a CycloneDX SBOM (`.cdx.json`), `SHA256SUMS` and the
   notes, which are the version's section of the changelog, word for word. GitHub signs a build
   provenance attestation for the files, and a GitHub Release publishes them, marked as a
   pre-release for an alpha, beta, release candidate or `.dev` version. The build refuses, and
   nothing is published, when the tag is not `pyproject.toml`'s version or the changelog has no
   section for it. Only the publishing job can write to the repository.

   To rehearse, run the workflow from the Actions tab (**Release**, **Run workflow**) or build
   locally with `python tools/release_build.py --dry-run --out dist`. A rehearsal builds from the
   declared version and the *Unreleased* notes, keeps the files as a workflow artifact for 14 days,
   and publishes nothing. Anyone can check a downloaded file with `sha256sum --check SHA256SUMS`
   and `gh attestation verify <file> -R eljaplacido/rihmastoai`.

   Rihmasto runs from a checkout (see `pyproject.toml`), so the source archive is the release:
   there is no wheel on PyPI and no container image of Rihmasto itself. The cockpit only ever
   listens on loopback, so an image would need its own decision first.

**If the squash message lost the trailer** (another default, or an edit), the sync still knows the
export by its title, "Sync from the development repository at `<short sha>`". If the title was
changed too, the squash reads as a contribution, and `import` records it as here already.

**If `main` moved while the sync pull request was open,** because a contribution merged meanwhile,
"require branches up to date" keeps it from merging. Close it, delete its branch (in the clone and
on GitHub), then import and export again. A sync pull request merged after `main` moved anyway
reads as a contribution; `import` records it with no change, since its snapshot is here already.

## When the sync refuses

| It says | What to do |
|---|---|
| A contribution waits for import (on `export`) | Run `import` first, then export again. |
| A contribution *touches* a path that release/exclude.txt keeps out (in any case) | The public repository must never hold that path. Bring in by hand what belongs here, in a commit with the contributor as its author (`git commit --author`), their sign-off, and a message that ends with `Rihmasto-Import: <public sha>`. The next export replaces the public tree with the snapshot, so the left-out path leaves the public `main` too. Tell the contributor on their pull request. |
| A path *differs only in case* from one here, or lands on a local file git does not track | On a disk that ignores case, git would file this repository's own files under the contributor's spelling, or overwrite your local file. Bring in by hand what belongs here, under this repository's spelling, as above. |
| It *changes* release/exclude.txt, a release tool or a .gitignore | Read the change on its pull request and in the clone. When it is sound, import with `--reviewed <public sha>`. |
| Its exclude list *would ship* a file left out here, or its .gitignore *would stop ignoring* a local file | Never import it, reviewed or not: the next export, or the next commit, would let those files out. Bring in by hand what belongs here, as above. |
| A file would fail the export's scans: a denylisted word, a secret, over 5 MB, a link to a left-out file | As above. A secret that reached the public repository is exposed: have it revoked and rotated at once, whatever the import does. |
| A *merge commit* | It was merged with a merge commit, so its author is whoever merged it. Bring the change in by hand with the contributor as its author and their sign-off, as above, and check that squash is the only merge method allowed. |
| A contribution does not apply cleanly | Its change meets a different change made here. The refusal prints the commands: save its patch, `git apply --3way` it, resolve the conflict, and commit it with its author kept (`git commit --author`) and a message that ends with its `Rihmasto-Import:` trailer. When nothing is left to commit, its change is here already: record it with the `git commit --allow-empty` command the refusal prints. Then import again for the rest; `--through` brings in the ones before it first. |
| Its message carries a `Rihmasto-Import` trailer | Only the sync writes that trailer, and only here. Bring that contribution in by hand, as above. |
| The branch `sync/<short sha>` exists already | That revision was exported before. Merge or close its pull request; delete the branch to export again. |
| The revision does not hold the last export, or the import of a contribution | Export a revision that holds both, normally `HEAD`. |
| The first export would delete files the public `main` has | See [Once: record the earlier snapshots](#once-record-the-earlier-snapshots). |
| The history cannot be read safely (exit 2) | A commit's text held the separator the sync reads git's output with. Report it; nothing was changed. |

The DCO check on the public pull requests is [tools/dco_check.py](../tools/dco_check.py), run by
[.github/workflows/dco.yml](../.github/workflows/dco.yml). A sync pull request passes it: the export
commit is signed off by its author. The owner's noreply address and Dependabot need no sign-off only
in pull requests their own accounts opened.
