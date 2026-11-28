"""Agent observability: what the IDE agents did in a project's repository, read from the team's own hub (FR-OBS1).

The owner (2026-11-24): "this should be a per-project view for the developer and maybe the IT persona; maybe not
on by default but a module to plug in, but still something embedded inside the platform."

The hub is an agent observability stack the team runs itself: its hooks in
Claude Code, Cursor and OpenCode record the metadata of each coding-agent session (what ran, where, how long, what
failed and what it touched; never a prompt, a response or a line of source) in a hash-chained ledger, and its
HTTP API answers read questions about it. Rihmasto reads that API and shows it inside the platform, per project:

- **settings** (this file): the hub's address, set by IT, kept in the factory's own canon. A loopback or private
  address, or one IT declares private, is read at once; a hosted address only with IT's explicit consent, over
  https. A token is named by its environment variable, never kept; the hub's reads need none by default;
- ``client``: the read-only HTTP client, the hub's API contract as Rihmasto uses it;
- ``mapping`` and ``detect``: which hub project is this project's (by the repository's catalog annotation, its
  git remote or its folder's name, or chosen by a person, recorded), and whether the repository carries the
  hub's hooks (by file names only, nothing opened or run);
- ``view`` and ``derive``: the Agent sessions view; ``snapshot``: a person's or an automation's record of what
  the hub showed; ``feeds``: what Insights, Review, the agent channel, the copilot and the checks read from it;
- ``ask``: Ask Rihma's answers; ``cli``: ``rihmasto agentobs``.

Rihmasto is the system of record for decisions and evidence, not for telemetry (D-0017): nothing here copies
the hub's events, and the module is off until a person turns it on (kernel/modules.py, ``optin``). It installs
nothing: instrumenting a repository is the hub's own command, which the view shows for a person to run.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from kernel.canon import DecisionRefused
from kernel.confidential import is_local
from kernel.people import is_person

MODULE = "agentobs"
VIEW = "agent_sessions"
SEES = ("developer", "it")                    # the personas the view is for
SETTERS = ("it",)                             # who sets the hub's address
MAPPERS = ("developer", "it")                 # who maps a project and records a snapshot
FILE = "agentobs.json"
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
DEFAULT_URL = "http://127.0.0.1:8787"         # the hub's own default (`npm run hub:dev`)
HUB = "the agent observability hub"


class HostedRefused(DecisionRefused):
    """A hosted hub address without IT's explicit consent."""


def module_on(target: Any) -> bool:
    """Whether the module is on for a project (its own set, or the factory's) or for the factory."""
    from kernel import modules

    return modules.is_on(target, MODULE)


def on_anywhere(factory: Any) -> bool:
    """Whether a person turned the module on for the factory or for any project."""
    from kernel.learn import FACTORY_PID

    return module_on(factory) or any(module_on(p) for p in factory.projects() if p.pid != FACTORY_PID)


def where(url: str, *, private: bool = False) -> str:
    """Where an address is: ``loopback``, ``private`` (a private network address or name), ``declared`` (IT says
    so) or ``hosted``."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in ("localhost", "::1") or host.startswith("127."):
        return "loopback"
    if is_local(url):
        return "private"
    return "declared" if private else "hosted"


def check_url(url: str, *, private: bool = False, hosted: bool = False) -> str:
    """The address as kept, or why not: http(s), a host, no credentials, query or fragment in it; a hosted one only
    with consent and over https."""
    text = url.strip().rstrip("/")
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"the hub's address is an http or https URL, such as {DEFAULT_URL}")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("the hub's address holds no credentials, query or fragment: name a token's environment "
                         "variable instead")
    if where(text, private=private) == "hosted":
        if not hosted:
            raise HostedRefused(f"{text} is a hosted address: the hub's records (file paths, session shapes) would "
                                "be read across the internet. IT consents explicitly to use it (`--hosted`, or "
                                "'I consent to a hosted hub' in Settings), or declares it private when it is on "
                                "your own network")
        if parts.scheme != "https":
            raise ValueError("a hosted hub is read over https only")
    return text


def settings(factory: Any) -> dict[str, Any]:
    """The hub's settings: its address (None until IT sets one), the token's environment variable name, whether IT
    declared it private or consented to a hosted one, and who set them."""
    from kernel.learn import factory_project

    store = factory_project(factory, create=False)
    saved = (store.read(FILE, None) if store is not None else None) or {}
    keys = ("url", "token_env", "private", "hosted_consent", "set_by", "persona", "at", "reason")
    out = {k: saved.get(k) for k in keys}
    out["where"] = where(out["url"], private=bool(out["private"])) if out["url"] else None
    return out


def set_settings(factory: Any, *, url: str, person: str, persona: str, token_env: str = "", private: bool = False,
                 hosted: bool = False, reason: str = "") -> dict[str, Any]:
    """IT sets (or, with an empty address, clears) the hub's address; recorded in the factory's ledger. The token's
    value is never read here, kept or recorded: only its environment variable's name."""
    from kernel.learn import factory_project

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: the hub's address is set by a named person")
    if persona not in SETTERS:
        raise DecisionRefused(f"a {persona} may not set the hub's address; IT does")
    token_env = token_env.strip()
    if token_env and not ENV_NAME.match(token_env):
        raise ValueError("the token is named by its environment variable (COCKPIT_HUB_TOKEN), never given itself")
    kept = check_url(url, private=private, hosted=hosted) if url.strip() else None
    store = factory_project(factory)
    at = factory.clock.stamp()
    consent = {"by": person, "persona": persona, "at": at} if kept and hosted and where(kept) == "hosted" else None
    doc = {"url": kept, "token_env": token_env or None, "private": bool(private and kept), "hosted_consent": consent,
           "set_by": person, "persona": persona, "at": at, "reason": reason.strip()[:300]}
    store.write(FILE, doc)
    store.log("agentobs_settings_set", {"url": kept, "token_env": doc["token_env"], "private": doc["private"],
                                        "hosted_consent": consent is not None, "where": where(kept, private=private)
                                        if kept else None, "person": person, "persona": persona,
                                        "reason": doc["reason"]})
    return settings(factory)
