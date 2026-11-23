#!/usr/bin/env python3
"""dco_check: every commit of a pull request is signed off under the Developer Certificate of Origin.

Standard library only, no model. CI runs it on each pull request (.github/workflows/dco.yml):

    python tools/dco_check.py --base <base sha> --head <head sha> --pr-author <login> [--repo .]

Every commit in base..head that is not a merge must carry a `Signed-off-by:` trailer whose name and
email are the commit author's (the email in any case). Two authors are exempt, each only in a pull
request its own GitHub account opened (`--pr-author`, which GitHub sets; git lets anyone write any
author address, so the address alone proves nothing): the project owner's GitHub noreply address,
because the owner holds the copyright of their own work, and dependabot[bot], whose changes are the
version bumps the owner asked it for. A failure lists each commit and says how to fix it: `git rebase
--signoff <the commit the branch starts from>`, then force-push the branch.

The commits are read with separators that carry a random token, so no commit's text can forge one,
and a count that differs from git rev-list's stops the check instead of skipping a commit.

Exit codes: 0 every commit is signed off or exempt; 1 a commit is not; 2 the check cannot run (an
unknown revision, no repository, a history it cannot read safely).
"""

from __future__ import annotations

import argparse
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

OWNER, OWNER_EMAIL = "eljaplacido", "40121627+eljaplacido@users.noreply.github.com"
DEPENDABOT, DEPENDABOT_EMAIL = "dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"
# An exempt author address: the account that must have opened the pull request, and why it is exempt.
EXEMPT = {OWNER_EMAIL: (OWNER, "the project owner, who holds the copyright"),
          DEPENDABOT_EMAIL: (DEPENDABOT, "dependabot[bot]")}
SIGNOFF = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>]*)>\s*$")
LOG_FIELDS = ("%H", "%an", "%ae", "%s", "%(trailers:key=Signed-off-by,valueonly,unfold)")


class CheckError(RuntimeError):
    """The check cannot run: an unknown revision, no repository, a history it cannot read safely."""


@dataclass(frozen=True)
class Commit:
    sha: str
    name: str
    email: str
    subject: str
    signoffs: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.sha[:12]} {self.subject} (by {self.name} <{self.email}>)"


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise CheckError(f"git {args[0]}: {detail}")
    return proc.stdout.decode("utf-8", "replace")


def resolve(repo: Path, rev: str) -> str:
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()
    except CheckError:
        raise CheckError(f"no commit {rev!r} in {repo}") from None


def commits(repo: Path, base: str, head: str) -> list[Commit]:
    """The commits in base..head that are not merges, oldest first; every one of them, or CheckError."""
    token = secrets.token_hex(16)
    record, sep = f"\x1e{token}\x1e", f"\x1f{token}\x1f"
    fmt = f"%x1e{token}%x1e" + f"%x1f{token}%x1f".join(LOG_FIELDS)
    raw = git(repo, "log", "--no-merges", "--reverse", f"--format={fmt}", f"{base}..{head}", "--")
    rows = [chunk.rstrip("\n").split(sep) for chunk in raw.split(record)[1:]]
    count = int(git(repo, "rev-list", "--no-merges", "--count", f"{base}..{head}", "--"))
    if len(rows) != count or any(len(row) != len(LOG_FIELDS) for row in rows):
        raise CheckError(f"read {len(rows)} records for the {count} commits in base..head: the check cannot run "
                         "safely")
    return [Commit(sha, name, email, subject, tuple(line.strip() for line in trailers.splitlines() if line.strip()))
            for sha, name, email, subject, trailers in rows]


def exemption(commit: Commit, opened_by: str | None) -> str | None:
    """Why the commit needs no sign-off: an exempt author address in a pull request its account opened."""
    login, why = EXEMPT.get(commit.email.strip().lower(), ("", ""))
    return why if login and opened_by is not None and opened_by.strip().lower() == login.lower() else None


def problem(commit: Commit) -> str | None:
    """What is wrong with the commit's sign-off, or None when it is signed off by its author."""
    if not commit.signoffs:
        return "no Signed-off-by trailer"
    author = (commit.name.strip(), commit.email.strip().lower())
    for value in commit.signoffs:
        m = SIGNOFF.match(value)
        if m and (m["name"].strip(), m["email"].strip().lower()) == author:
            return None
    shown = "; ".join(commit.signoffs)
    return f"its Signed-off-by ({shown}) is not its author, {commit.name} <{commit.email}>"


def fork_point(repo: Path, base: str, head: str) -> str:
    """The last commit the branch shares with the target branch: every clone of the branch has it."""
    proc = subprocess.run(["git", "-C", str(repo), "merge-base", base, head], capture_output=True, check=False)
    return proc.stdout.decode("ascii", "replace").strip() if proc.returncode == 0 else base


def how_to_fix(start: str) -> list[str]:
    return ["How to fix it: sign off every commit on your branch, then force-push the branch:",
            f"  git rebase --signoff {start[:12]}",
            "  git push --force-with-lease origin HEAD",
            f"{start[:12]} is where your branch starts, the last commit it shares with the target branch, so the",
            "rebase moves nothing and only adds the sign-off lines. `git rebase --signoff` signs with your git",
            "user.name and user.email, so they must be the name and email the commits are authored with.",
            "CONTRIBUTING.md, \"Licence and sign-off\", says what the sign-off certifies."]


def check(repo: Path, base: str, head: str, opened_by: str | None = None) -> tuple[int, list[str]]:
    """(exit code, the lines to print). ``opened_by`` is the pull request author's GitHub login."""
    base, head = resolve(repo, base), resolve(repo, head)
    found = commits(repo, base, head)
    lines: list[str] = []
    failed: list[str] = []
    for commit in found:
        why = exemption(commit, opened_by)
        if why:
            lines.append(f"exempt: {commit}: authored by {why}, in a pull request {opened_by} opened")
            continue
        wrong = problem(commit)
        login = EXEMPT.get(commit.email.strip().lower(), ("", ""))[0]
        if wrong and login:
            wrong += f" (its author address is exempt only in a pull request {login} opened)"
        if wrong:
            failed.append(f"  {commit}: {wrong}")
    if failed:
        lines += [f"DCO: {len(failed)} of {len(found)} commit(s) are not signed off by their author:", *failed, "",
                  *how_to_fix(fork_point(repo, base, head))]
        return 1, lines
    lines.append(f"DCO: {len(found)} commit(s) checked, every one signed off by its author or exempt"
                 if found else "DCO: no commits to check (merges are not checked)")
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/dco_check.py",
                                 description="Check that every commit in base..head is signed off by its author.")
    ap.add_argument("--base", required=True, help="the target branch's commit the pull request is checked against")
    ap.add_argument("--head", required=True, help="the pull request's last commit")
    ap.add_argument("--pr-author", help="the GitHub login that opened the pull request; without it, nobody is exempt")
    ap.add_argument("--repo", type=Path, default=Path("."), help="the repository (default: the current folder)")
    args = ap.parse_args(argv)
    try:
        code, lines = check(args.repo, args.base, args.head, args.pr_author)
    except CheckError as exc:
        print(f"dco_check: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
