"""About and help (FR-PUB2): which Rihmasto this is, whether this machine can run it, and where the guides are.

Settings, About and help shows it (cockpit/about_routes.py, cockpit/static/about.js); Ask Rihma answers the same
questions from it by rule (kernel/assistant_help.py); a terminal has ``rihmasto --version`` and ``rihmasto
doctor``. Nothing here writes: the machine check is kernel/doctor.py's report, trimmed to what a person reads
(no executable paths, no key values: doctor never reads one).
"""

from __future__ import annotations

from typing import Any

from kernel.version import ROOT, is_prerelease, rihmasto_version

PUBLIC = "https://github.com/eljaplacido/rihmastoai/blob/main/"

# The guides a person asks for, by id: (title, path in the checkout, #anchor, who it is for, what it says).
DOCS: dict[str, tuple[str, str, str, str, str]] = {
    "index": ("All documentation", "docs/README.md", "", "everyone", "every guide, by scenario and by part"),
    "start": ("Getting started", "docs/getting-started.md", "", "everyone",
              "install Rihmasto and Gnomon, check the machine, choose the models, the first run"),
    "verify": ("Verify what you install", "docs/getting-started.md", "verify-what-you-install", "everyone",
               "check Gnomon's checksums and build provenance before you trust it, and Rihmasto's own releases"),
    "scenarios": ("Use scenarios", "docs/scenarios/README.md", "", "everyone",
                  "start blank, bring in a project, improve it, fix an ungoverned one, automate"),
    "ungoverned": ("Fix a project that lacks governance", "docs/scenarios/fix-ungoverned-project.md", "", "everyone",
                   "bring governance, reliability and traceability back step by step, without stopping the work"),
    "structure": ("How much structure to take on", "docs/scenarios/existing-project.md",
                  "how-much-structure-to-take-on", "everyone",
                  "the five levels, from Watch only to the Full chain, and what each asks of you"),
    "contributing": ("Contributing", "CONTRIBUTING.md", "", "contributors",
                     "sign-off, set-up, the checks, spec first, how a change reaches main"),
    "architecture": ("Architecture", "docs/architecture.md", "", "contributors",
                     "the layers and the code behind each"),
    "maintainers": ("Maintainers: releases and the sync", "docs/maintainers.md", "", "maintainers",
                    "the repository's settings, the two-way sync, tagging a version"),
    "changelog": ("Changelog", "CHANGELOG.md", "", "everyone", "what changed in each version"),
}
COMMANDS = {"version": "rihmasto --version", "doctor": "rihmasto doctor"}


def doc(doc_id: str) -> dict[str, Any]:
    """One guide: its title, where it is in this checkout and on GitHub, who it is for and what it says."""
    title, path, anchor, who, says = DOCS[doc_id]
    hash_ = f"#{anchor}" if anchor else ""
    local = ROOT / path
    return {"id": doc_id, "title": title, "path": path + hash_, "url": PUBLIC + path + hash_, "for": who,
            "says": says, "local": str(local) if local.exists() else None}


def view() -> dict[str, Any]:
    """What Settings, About and help shows: the version, the commands and the guides."""
    version = rihmasto_version()
    return {"version": version, "prerelease": is_prerelease(version), "commands": dict(COMMANDS),
            "docs": [doc(d) for d in DOCS]}


def machine(home: Any, **kw: Any) -> dict[str, Any]:
    """This machine's check (kernel/doctor.py), as a person reads it: versions, problems and warnings."""
    from kernel.doctor import doctor

    report = doctor(home, **kw)
    g, git, docker = report["gnomon"], report["git"], report["docker"]
    return {"rihmasto": report["rihmasto"], "python": {"found": True, "version": report["python"]["version"],
                                                       "ok": report["python"]["ok"]},
            "gnomon": {"found": g["found"], "version": g.get("version"), "supported": g.get("supported", False),
                       "min": g.get("min"), "recommended": g.get("recommended")},
            "git": {"found": git["found"], "version": git.get("version")},
            "docker": {"found": docker["found"], "version": docker.get("version")},
            "problems": list(report["problems"]), "warnings": list(report["warnings"]), "ok": report["exit"] == 0,
            "command": COMMANDS["doctor"]}
