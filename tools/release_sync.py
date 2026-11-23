#!/usr/bin/env python3
"""release_sync: keeps this repository and the public one in step, both ways.

Standard library only, no model; git 2.40 or later. The public repository holds scrubbed snapshots of
this one, made with tools/release_export.py, and takes contributions as squash-merged pull requests. This
tool brings the merged contributions in here, and sends each new snapshot out as a pull request:

    python tools/release_sync.py status --public ../public-clone
    python tools/release_sync.py import --public ../public-clone [--through SHA] [--reviewed SHA ...]
    python tools/release_sync.py export --public ../public-clone [--rev HEAD] [--pr] [--allow-deletions]

How a public commit is read, as an export or a contribution: tools/release_state.py. In short, an export
names the revision it is the snapshot of (a `Rihmasto-Export: <full sha>` trailer, or the sync pull
request's title), its tree is that snapshot, and the revision comes after the last export's; anything
else is a contribution, so copying the trailer never skips an import. An import is recorded here by the
trailer `Rihmasto-Import: <public sha>` on the commit that brought the contribution in.

status fetches the clone's origin and lists the public commits after the last export not yet imported.
import brings them in, oldest first; tools/release_import.py says how, and what it refuses before it
changes anything. export refuses while a contribution waits, when the revision lacks an import recorded
since the last export, or when it does not hold the last export (an export must never revert work the
public repository has); the first export after the earlier snapshots were recorded by hand also refuses
to delete public files without --allow-deletions. It scans the snapshot and commits it with the export
trailer on a new branch sync/<short sha> made from the public main. With --pr it pushes the branch and
opens a pull request with gh; without, it prints the commands to run.

Exit codes: 0 done; 1 refused, nothing changed; 2 the sync cannot run (no clone, an unknown revision,
no denylist, a git or gh failure).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_export as rx  # noqa: E402
import release_import  # noqa: E402
from release_state import (  # noqa: E402
    EXPORT_KEY,
    IMPORT_KEY,
    PublicCommit,
    Refused,
    State,
    Sync,
    export_note,
    git,
    holds,
    imported,
    listing,
    public_only,
    snapshot_tree,
    state,
    text,
)

# -- status -------------------------------------------------------------------------------------

def bootstrap_hint(sync: Sync, waiting: list[PublicCommit]) -> list[str]:
    trailers = " ".join(f'--trailer "{IMPORT_KEY}: {c.sha}"' for c in waiting)
    lines = ["No export was found, so every public commit counts as a contribution. If these commits are",
             "snapshots made before release_sync, already in this repository, record them once as imported:",
             f'  git commit --allow-empty -m "Record the public history made before release_sync" {trailers}',
             "Never record a real contribution that way: import it."]
    head = text(sync.private, "rev-parse", "HEAD")
    lacking = public_only(sync, snapshot_tree(sync, head) or head)
    if lacking:
        lines += [f"Careful: HEAD's snapshot lacks {len(lacking)} file(s) the public {sync.branch} has: "
                  f"{listing(lacking)}.",
                  "Record the snapshots only once HEAD holds every one of them (merge the branch the last one was",
                  "made from first): the first export would delete those files from the public repository."]
    return lines


def status(sync: Sync) -> int:
    st = state(sync)
    print(f"public {sync.branch}: {st.head[:12]}")
    if st.last_export and st.exported:
        print(f"the last export: {st.last_export.sha[:12]}, the snapshot of {st.exported[:12]}")
    else:
        print(f"the last export: none found (no public commit names, in a {EXPORT_KEY} trailer or its title, a "
              "revision HEAD holds and is its snapshot)")
    if not st.waiting:
        print("nothing waits for import")
        return 0
    print(f"waiting for import, oldest first ({len(st.waiting)}):")
    for commit in st.waiting:
        note = export_note(sync, commit)
        print(f"  {commit}" + (f"\n      {note}" if note else ""))
    print(f"next: python tools/release_sync.py import --public {sync.clone}")
    if st.last_export is None:
        print("\n".join(bootstrap_hint(sync, st.waiting)))
    return 0


# -- export -------------------------------------------------------------------------------------

def export_message(sync: Sync, rev: str) -> tuple[str, str]:
    """The export's title and body; the body ends with the export trailer."""
    ident = text(sync.clone, "var", "GIT_AUTHOR_IDENT").rsplit(" ", 2)[0]
    title = f"Sync from the development repository at {rev[:12]}"
    body = ("A snapshot of the maintainers' development repository, made with tools/release_sync.py.\n\n"
            "Every contribution merged on the public main was brought into the development repository "
            "before this export, so it reverts none of them.\n\n"
            f"Signed-off-by: {ident}\n{EXPORT_KEY}: {rev}")
    return title, body


def run_gh(cwd: Path, args: list[str]) -> int:
    """Run the GitHub CLI in the public clone; its output goes to the terminal."""
    try:
        return subprocess.run(["gh", *args], cwd=cwd, check=False).returncode
    except FileNotFoundError:
        raise rx.ExportError("gh, the GitHub CLI, is not installed: open the pull request by hand") from None


def check_exportable(sync: Sync, st: State, rev: str) -> None:
    """Refuse an export that would revert a contribution or go back before the last export."""
    if st.waiting:
        raise Refused([f"refused: {len(st.waiting)} contribution(s) merged on the public {sync.branch} wait "
                       "for import:", *(f"  {c}" for c in st.waiting),
                       "An export must never revert a contribution: run import first, then export again."])
    if st.exported and not holds(sync, rev, st.exported):
        raise Refused([f"refused: {rev[:12]} does not hold {st.exported[:12]}, the last export; exporting it "
                       "would undo work the public repository has."])
    held = imported(sync, rev)
    missing = [c for c in st.after if c.sha not in held]
    if missing:
        raise Refused([f"refused: {rev[:12]} does not hold the import of {len(missing)} contribution(s) merged on "
                       f"the public {sync.branch} since the last export:", *(f"  {c}" for c in missing),
                       "Exporting it would revert them: export HEAD, or a revision that holds their imports."])


def check_deletions(sync: Sync, st: State, tree: str, allow: bool) -> list[str]:
    """The public files the export deletes; the first export refuses to delete any without ``allow``."""
    gone = public_only(sync, tree)
    if gone and st.last_export is None and not allow:
        raise Refused([f"refused: this first export would delete {len(gone)} file(s) the public {sync.branch} has: "
                       f"{listing(gone, 10)}",
                       "HEAD may not hold the latest snapshot: merge the branch it was made from, then export again.",
                       "When the deletions are meant, export with --allow-deletions."])
    return gone


def export(sync: Sync, rev: str, pr: bool, allow_deletions: bool = False) -> int:
    st = state(sync)
    snap = rx.build(sync.private, rev, sync.denylist)
    check_exportable(sync, st, snap.commit)
    if snap.hits:
        hits = sorted(snap.hits, key=lambda h: (h.path, h.line, h.kind, h.detail))
        raise Refused([*(rx.mask_words(str(h), snap.words) for h in hits),
                       f"refused: {len(hits)} problem(s) in the snapshot of {snap.commit[:12]}; nothing was written"])
    tree = snapshot_tree(sync, snap.commit)
    base, public_tree = text(sync.clone, "rev-parse", sync.ref, f"{sync.ref}^{{tree}}").split()
    if tree is None or tree == public_tree:
        print(f"nothing to export: the public {sync.branch} already holds the snapshot of {snap.commit[:12]}")
        return 0
    gone = check_deletions(sync, st, tree, allow_deletions)
    branch = f"sync/{snap.commit[:12]}"
    if text(sync.clone, "for-each-ref", f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        raise Refused([f"refused: {branch} exists already, from an earlier export of this revision. Close its "
                       "pull request or merge it; delete the branch to export again."])
    objects = git(sync.private, "rev-list", "--objects", tree)
    git(sync.clone, "index-pack", "--stdin", data=git(sync.private, "pack-objects", "-q", "--stdout", data=objects))
    title, body = export_message(sync, snap.commit)
    commit = text(sync.clone, "commit-tree", tree, "-p", base, "-F", "-", data=f"{title}\n\n{body}\n".encode())
    git(sync.clone, "branch", branch, commit)
    print(f"exported {snap.commit[:12]} ({len(snap.files)} files) as {commit[:12]} on {branch}, made from the public "
          f"{sync.branch} at {base[:12]}")
    if gone:
        print(f"it deletes {len(gone)} file(s) from the public {sync.branch}: {listing(gone, 10)}")
    if not pr:
        print("next, to open the pull request (its description ends with the export trailer):",
              f'  git -C "{sync.clone}" push origin {branch}', f'  cd "{sync.clone}"',
              f"  gh pr create --base {sync.branch} --head {branch} --fill", sep="\n")
        return 0
    git(sync.clone, "push", "--quiet", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    code = run_gh(sync.clone, ["pr", "create", "--base", sync.branch, "--head", branch,
                               "--title", title, "--body", body])
    if code != 0:
        raise rx.ExportError(f"gh pr create failed (exit {code}); {branch} is pushed: open its pull request by hand")
    return 0


# -- the command line ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--public", type=Path, required=True,
                        help="a clone of the public repository, kept for releases (its origin is fetched)")
    common.add_argument("--repo", type=Path, default=rx.ROOT, help="this repository (default: this checkout)")
    common.add_argument("--branch", default="main", help="the public repository's protected branch (default: main)")
    deny = common.add_mutually_exclusive_group()
    deny.add_argument("--denylist", type=Path,
                      help=f"the denylist (default: {rx.DENYLIST_NAME} at the repository root)")
    deny.add_argument("--no-denylist", action="store_true", help="skip the denylist scan; the report says so")
    ap = argparse.ArgumentParser(prog="python tools/release_sync.py",
                                 description="Keep this repository and the public one in step, both ways.")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status", parents=[common], help="list the public contributions waiting for import")
    imp = sub.add_parser("import", parents=[common], help="bring the waiting contributions in, oldest first")
    imp.add_argument("--through", help="import the waiting contributions up to this public commit only")
    imp.add_argument("--reviewed", action="append", default=[], metavar="SHA",
                     help="a waiting contribution that changes release/exclude.txt, a release tool or a .gitignore, "
                          "which you have read (repeatable)")
    exp = sub.add_parser("export", parents=[common], help="commit a snapshot on a sync branch of the public clone")
    exp.add_argument("--rev", default="HEAD", help="the revision to export (default: HEAD)")
    exp.add_argument("--pr", action="store_true", help="push the branch and open a pull request with gh")
    exp.add_argument("--allow-deletions", action="store_true",
                     help="let the first export delete public files HEAD's snapshot does not hold")
    return ap.parse_args(argv)


def work_tree(path: Path) -> tuple[Path, Path]:
    """(the top of the work tree at ``path``, the git folder it shares with its other work trees)."""
    top, common = text(path, "rev-parse", "--show-toplevel", "--git-common-dir").splitlines()
    return Path(top), (path / common).resolve()


def open_sync(args: argparse.Namespace) -> Sync:
    private, mine = work_tree(args.repo)
    if not args.public.is_dir():
        raise rx.ExportError(f"no public clone at {args.public}")
    clone, theirs = work_tree(args.public)
    if mine == theirs:
        raise rx.ExportError(f"{args.public} is this repository or a work tree of it, not a clone of the public one")
    return Sync(private, clone, args.branch, rx.denylist_of(args, private))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sync = open_sync(args)
        if args.command == "status":
            return status(sync)
        if args.command == "import":
            return release_import.import_contributions(sync, args.through, args.reviewed)
        return export(sync, args.rev, args.pr, args.allow_deletions)
    except Refused as exc:
        print("\n".join(exc.lines))
        return 1
    except rx.ExportError as exc:
        print(f"release_sync: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
