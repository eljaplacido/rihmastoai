"""Ask Rihma's answers about Rihmasto itself (FR-PUB2), by rule, model or not: which version this is, how to check
what you install, how to fix a project that has no governance, how much structure to take on, how to contribute,
and where the guides are.

These questions used to land on whatever map entry shared a word ("verify" found the Cell view, "version" the
Runners view, "docs for contributors" the Outputs view) or on "could not match". Each now gets a plain answer, the
steps, the guide it comes from (in this checkout and on GitHub), the command where there is one, and Take me there
to the place in the cockpit that does the same: Settings, About and help for the version, the machine check and
the guides; the project's Alignment for the structure; Projects, adopt, for a project not brought in yet.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import about

ABOUT_NAV = {"route": "#/settings", "control": "about_help"}

_VERSION = re.compile(r"\b(?:what|which)\s+version\b|\bversion\s+of\s+(?:rihmasto|rihma)\b|"
                      r"\b(?:rihmasto|rihma)(?:'s)?\s+version\b|--version\b|\bam\s+i\s+(?:running|on)\b.*\bversion\b|"
                      r"\bmikä\s+versio\b", re.I)
_SELF = re.compile(r"\b(?:rihmasto|rihma|this|running|installed|i\s+have|am\s+i|is\s+it)\b|--version|versio", re.I)
_OTHER_VERSION = re.compile(r"\b(?:pack|capability|release\s+package|spec|contract|model|python|node|api)\b", re.I)
_STRONG = re.compile(r"\b(?:checksums?|sha-?256\w*|sha256sums|attestations?|provenance)\b", re.I)
_VERIFY = re.compile(r"\b(?:verify|verif\w+|tarkist\w*)\b", re.I)
_INSTALL = re.compile(r"\b(?:gnomon|install\w*|download\w*|binary|binaries|installer|asennu\w*)\b", re.I)
_NOT_INSTALL = re.compile(r"\b(?:pack|evidence|bundle|ledger|chain|audit)\b", re.I)
_DOCTOR = re.compile(r"(?<!gnomon\s)\bdoctor\b|\bis\s+my\s+(?:install\w*|setup|machine)\s+(?:ok|working|right|fine)\b|"
                     r"\bcan\s+this\s+machine\s+run\b|\bcheck\s+(?:my|this)\s+(?:machine|install\w*|computer)\b", re.I)
_UNGOVERNED = re.compile(r"\b(?:no|without|lacks?|lacking|missing|zero|poor|little)\s+(?:\w+\s+){0,2}"
                         r"(?:governance|traceability)\b|\bungoverned\b|\bnot\s+governed\b", re.I)
_FIX = re.compile(r"\b(?:fix|repair|govern|bring|clean|rescue|tame|add|get|put|improve|korja\w*)\b", re.I)
_STRUCTURE = re.compile(r"\bhow\s+(?:much|far)\b.{0,40}\b(?:structure|governance|enforce\w*|rigou?r)\b|"
                        r"\b(?:structure|governance)\s+levels?\b|\blevels?\s+of\s+(?:structure|governance|adoption)\b|"
                        r"\bfive\s+levels\b", re.I)
_CONTRIBUTE = re.compile(r"\bcontribut(?:e|ing|ion|ions)\b|\bsend\s+a\s+(?:pull\s+request|pr|patch)\s+to\s+rihmasto\b|"
                         r"\bsign[- ]off\s+(?:my\s+)?commits?\b", re.I)
_DOCS = re.compile(r"\b(?:docs|documentation|guides|manual|handbook|dokumentaatio\w*|ohjeet)\b|"
                   r"\bthe\s+guide\s+(?:for|to|on|about)\b", re.I)
_DOCS_ASK = re.compile(r"\b(?:where|which|what|find|show|read|link|is\s+there|are\s+there|any|open)\b", re.I)
_DEVS = re.compile(r"\b(?:contributors?|developers?|maintainers?|architecture|codebase|internals?)\b", re.I)


def _out(answer: str, steps: list[dict[str, Any]], docs: list[str], nav: dict[str, Any], topic: str) -> dict[str, Any]:
    return {"answer": answer, "steps": steps, "docs": [about.doc(d) for d in docs], "navigate": nav, "propose": [],
            "dropped": [], "sources": [about.doc(d)["path"] for d in docs], "by": "rule",
            "matches": ["about_help"], "topic": topic}


def _guide_step(docs: list[str]) -> dict[str, Any]:
    named = "; ".join(f"{about.doc(d)['title']}: {about.doc(d)['path']}" for d in docs)
    return {"text": f"Read more in {named} (in the folder Rihmasto runs from, and on GitHub)."}


def version_answer() -> dict[str, Any]:
    info = about.view()
    alpha = " It is an alpha: see the changelog for what is and is not ready." if info["prerelease"] else ""
    return _out(f"This is Rihmasto {info['version']}.{alpha} Settings › About and help shows it, with a check of "
                "this machine (Python, Gnomon, git, docker).",
                [{"text": "Open Settings › About and help (Take me there opens it).", "action": "navigate"},
                 {"text": "Or from a terminal, in the folder Rihmasto runs from:",
                  "commands": [about.COMMANDS["version"], about.COMMANDS["doctor"]]},
                 _guide_step(["changelog"])], ["changelog"], ABOUT_NAV, "version")


def verify_answer() -> dict[str, Any]:
    return _out("Check Gnomon's bytes before you trust them: its installer refuses a file whose SHA-256 does not "
                "match the release's SHA256SUMS, and you can check a release by hand with sha256sum and gh "
                "attestation verify. Then rihmasto doctor says which Gnomon it found and whether it is supported; "
                "Settings › About and help runs the same check here.",
                [{"text": "Download the release's archive and its SHA256SUMS, then check both (here for Gnomon "
                          "0.6.7 on Linux):",
                  "commands": ["gh release download v0.6.7 -R eljaplacido/gnomonharness "
                               "-p gnomon-0.6.7-linux-x64.tar.gz -p SHA256SUMS",
                               "sha256sum --check --ignore-missing SHA256SUMS",
                               "gh attestation verify gnomon-0.6.7-linux-x64.tar.gz --repo eljaplacido/gnomonharness"]},
                 {"text": "On Windows, Get-FileHash gnomon-0.6.7-windows-x64.tar.gz -Algorithm SHA256 prints the "
                          "hash to compare with its line in SHA256SUMS."},
                 {"text": "Then check this machine: Settings › About and help › Check this machine (Take me there "
                          "opens it), or rihmasto doctor in a terminal.", "action": "navigate",
                  "commands": [about.COMMANDS["doctor"]]},
                 {"text": "A Gnomon surface that grants more than its defaults needs its owner's trust "
                          "(gnomon trust grant): give it yourself, never through an agent."},
                 _guide_step(["verify"])], ["verify"], ABOUT_NAV, "verify")


def doctor_answer() -> dict[str, Any]:
    return _out("Settings › About and help › Check this machine runs rihmasto doctor here: Rihmasto's version, "
                "Python, Gnomon (0.6.5 or later), git and docker, with each problem and what to do about it.",
                [{"text": "Open Settings › About and help and press Check this machine (Take me there opens it).",
                  "action": "navigate"},
                 {"text": "Or from a terminal:", "commands": [about.COMMANDS["doctor"]]},
                 _guide_step(["start"])], ["start"], ABOUT_NAV, "doctor")


def _project_nav(project: Any, view: str) -> dict[str, Any]:
    from kernel.assistant_rules import FACTORY_PID

    if project is not None and project.pid != FACTORY_PID:
        return {"route": f"#/p/{project.pid}/{view}", "control": None}
    return {"route": "#/projects", "control": "adopt_project"}


def ungoverned_answer(project: Any) -> dict[str, Any]:
    nav = _project_nav(project, "align")
    where = ("Open its Alignment (Take me there opens it)." if nav["control"] is None else
             "Open Projects › New project › An existing project (Take me there opens it).")
    return _out("Bring governance back step by step, without stopping the work; you can stop at any step: "
                "1 capture what is there at Watch only, changing nothing; 2 measure it (Assessment, a security "
                "scan); 3 write down what it must do (Alignment turns its own specs and tests into a contract); "
                "4 put the agents under that contract (AI tools, the IDE set-up); 5 gate every change; 6 keep it "
                "traceable (Evidence, Track).",
                [{"text": where, "action": "navigate"},
                 {"text": "Bring it in at Watch only first: nothing changes in how you work (from a terminal, "
                          "rihmasto adopt with --intent monitor)."},
                 _guide_step(["ungoverned", "structure"])], ["ungoverned", "structure"], nav, "ungoverned")


def structure_answer(project: Any) -> dict[str, Any]:
    nav = _project_nav(project, "align")
    return _out("As much as helps, no more: there are five levels, and each is useful on its own. Watch only (an "
                "inventory, a test baseline, findings; nothing changes in how you work). Captured (where its specs, "
                "decisions and tests are). Aligned (a contract made of your own specs and tests, gaps and drift "
                "listed). Gated (a verdict on each change before you merge). Full chain (changes built and merged "
                "only through the gate, with packs and evidence). Start at Watch only and move up when a level "
                "pays for itself.",
                [{"text": ("Open its Alignment: it shows where the project is now (Take me there opens it)."
                           if nav["control"] is None else
                           "Bring the project in first at Watch only: Projects › New project › An existing "
                           "project (Take me there opens it)."), "action": "navigate"},
                 _guide_step(["structure"])], ["structure"], nav, "structure")


def contribute_answer() -> dict[str, Any]:
    return _out("Rihmasto takes contributions as pull requests on GitHub, under Apache-2.0 with a DCO sign-off on "
                "every commit (git commit -s). Read CONTRIBUTING.md first: how to set up, run the checks, write the "
                "criterion and its test before the change, and how a change reaches main.",
                [{"text": "Fork the repository, make a branch, and sign off every commit:",
                  "commands": ["git commit -s", "python tools/quality.py --gate"]},
                 {"text": "Open Settings › About and help for the guides (Take me there opens it).",
                  "action": "navigate"},
                 _guide_step(["contributing", "architecture"])], ["contributing", "architecture"], ABOUT_NAV,
                "contribute")


def docs_answer(question: str) -> dict[str, Any]:
    devs = bool(_DEVS.search(question))
    docs = ["contributing", "architecture", "maintainers", "index"] if devs else ["index", "start", "scenarios"]
    lead = ("For contributors: CONTRIBUTING.md (set-up, checks, how a change reaches main), docs/architecture.md "
            "(the layers and their code) and docs/maintainers.md (releases)." if devs else
            "The documentation starts at docs/README.md, every guide by scenario and by part; begin with Getting "
            "started and the use scenarios.")
    return _out(lead + " Settings › About and help lists them with their links.",
                [{"text": "Open Settings › About and help (Take me there opens it).", "action": "navigate"},
                 _guide_step(docs[:2])], docs, ABOUT_NAV, "docs")


def _asks_version(q: str) -> bool:
    return bool(_VERSION.search(q)) and bool(_SELF.search(q)) and not _OTHER_VERSION.search(q)


def _asks_verify(q: str) -> bool:
    return bool(_STRONG.search(q) or (_VERIFY.search(q) and _INSTALL.search(q))) and not _NOT_INSTALL.search(q)


def _asks_ungoverned(q: str) -> bool:
    return bool(_UNGOVERNED.search(q) and _FIX.search(q))


def _asks_contribute(q: str) -> bool:
    return bool(_CONTRIBUTE.search(q)) and not _OWN_PROJECT.search(q)


def _asks_docs(q: str) -> bool:
    return bool(_DOCS.search(q) and _DOCS_ASK.search(q))


_OWN_PROJECT = re.compile(r"\bcontribut\w*\s+to\s+(?:it|this|my|the\s+(?:project|code))", re.I)
# In order: the first question it asks is the one answered.
RULES = ((_asks_version, lambda q, p: version_answer()), (_asks_verify, lambda q, p: verify_answer()),
         (lambda q: bool(_DOCTOR.search(q)), lambda q, p: doctor_answer()),
         (lambda q: bool(_STRUCTURE.search(q)), lambda q, p: structure_answer(p)),
         (_asks_ungoverned, lambda q, p: ungoverned_answer(p)), (_asks_contribute, lambda q, p: contribute_answer()),
         (_asks_docs, lambda q, p: docs_answer(q)))


def answer(question: str, project: Any = None) -> dict[str, Any] | None:
    """The answer about Rihmasto itself the question asks for, or None (it is not about that)."""
    q = " ".join(str(question or "").split())
    return next((make(q, project) for asks, make in RULES if q and asks(q)), None)


def routed(question: str, project: Any, about_: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ask Rihma's hook (kernel/assistant.py ``ask``): an answer already found stays, else this one, or None."""
    return about_ if about_ is not None else answer(question, project)
