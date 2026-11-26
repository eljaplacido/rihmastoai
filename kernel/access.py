"""Who may decide as which persona, on which project (D-0016, FR-M8, FR-ID1).

Rihmasto never stores passwords. People sign in through the organisation's identity provider (OIDC) at an
identity-aware proxy IT runs beside the cockpit, which forwards the provider's signed token; the cockpit
verifies it with the provider's public keys (``kernel.access_tokens``). On the operator's own machine the
command line and the MCP server sign as the operating system's user (``local:<os user>``). What an identity may act as is an IT-owned
access map, ``projects/_factory/access/access.json`` (``rihmasto.access/1``, ``kernel.accessfile``), in a
folder of its own that IT alone writes: the kernel only reads it, and keeps its locks beside the factory
ledger. Two modes:
- **single_operator**, the default while no file exists: today's behaviour, unchanged. Whoever holds
  the cockpit's session or the command line names a person and picks a persona, and the cockpit's
  header and ``rihmasto status`` say so: "single operator: personas are self-declared".
- **enforced**: a write that records a person's decision or answer is signed by a verified identity,
  as a persona a binding grants it on that project (scope "*" is every project, the factory's own canon
  ``_factory`` included). The person is the identity's display name; a different name is refused.

``sign`` is the one check every surface makes (the cockpit's JSON API, the command line, the MCP
server), and ``require`` is the kernel's own check behind them, on every card and question decision and
on pause and resume. A record's identity is as strong as the factory home's file permissions: code
running as an account that can write the home can write any record.

Rihmasto fails closed. A file that cannot be read or checked refuses every decision, whatever mode it
names; so does a missing file once access was enforced, which the factory ledger's last
``access_changed`` record, the access folder left without its file, or a project ledger holding a
decision signed by a verified identity shows. Each change of the file is recorded in the factory ledger
the first time a write loads it: its sha256, what the file claims about who changed it, the file's owner
and modification time as the file system has them, and which surface and identity noticed it.

There is no shared secret: the key file holds public keys, so nothing this process can read lets anyone
sign in as someone else. While access is enforced, code a model or a developer wrote runs only through
the isolation runner the file names (``kernel.access_isolation``). Card-kind rules
(``kernel.canon.CARD_DECIDERS``) still apply on top. Machine identity for roads and lanes stays with
Gnomon (D-0015).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

from kernel.access_tokens import Headers, signed_in, with_keys
from kernel.accessfile import (  # noqa: F401  (MODES, SCHEMA and SESSION_HEADER are re-exported)
    ALL,
    ENFORCED,
    FACTORY_SCOPE,
    LOCAL,
    MODES,
    SCHEMA,
    SESSION_HEADER,
    SINGLE,
    Access,
    AccessFileError,
    Binding,
    parse,
)
from kernel.canon import DecisionRefused
from kernel.jwt_verify import TokenRefused
from kernel.ledgerstore import LedgerStore
from kernel.name_skeleton import disguised, skeleton, visible
from kernel.osuser import file_owner, os_user
from kernel.people import PERSONAS, SIGNER, Identity
from kernel.store import Factory, Project, lock_path, records_lock

SINGLE_NOTE = "single operator: personas are self-declared"
CHANGED = "access_changed"          # the factory ledger's record of a changed access file
ACCESS_DIR = "access"               # the access file's own folder, in projects/_factory
# A record a verified identity signed: its identity is local:<os user> or <issuer>#<subject>.
_SIGNED = re.compile(rb'"identity":"(?:local:|https://)')


class AccessRefused(DecisionRefused):
    """A write the access rules refuse: no verified identity, a persona not granted on the project, or
    a person who is not the signed-in identity. The cockpit answers 401 or 403; the CLI exits 2."""


class AccessBroken(AccessRefused):
    """Access is enforced but cannot be applied (the file cannot be read or checked; for the cockpit's
    sign-in, the provider's key file): what it guards is refused until IT fixes it."""


# -- the file ------------------------------------------------------------------------------------------

def access_path(factory: Factory) -> Path:
    return factory.projects_dir / FACTORY_SCOPE / ACCESS_DIR / "access.json"


_PARSED: dict[str, Access] = {}                      # sha256 of a file's bytes -> what it says
_LAST: dict[str, tuple[tuple[int, int], dict | None]] = {}   # ledger path -> (its size and time, last change)
_SCANNED: dict[str, tuple[int, bool]] = {}           # project ledger -> (bytes read, a signed record seen)


def _closed(why: str) -> Access:
    return Access(ENFORCED, error=why)


def _parsed(raw: bytes) -> Access:
    sha = hashlib.sha256(raw).hexdigest()
    if sha not in _PARSED:
        try:
            parsed = parse(raw)
        except AccessFileError as exc:
            parsed = _closed(f"the access file is not valid: {exc}")
        if len(_PARSED) > 64:
            _PARSED.clear()
        _PARSED[sha] = replace(parsed, sha256=sha)
    return _PARSED[sha]


def load(factory: Factory, *, record: bool = False, by: str = "the kernel") -> Access:
    """The access rules now. ``record`` notes a changed (or removed) file in the factory ledger first;
    every write path passes it, so a change is on record before any decision is taken under it."""
    path = access_path(factory)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        access = _missing(factory, path)
    except OSError as exc:
        access = _closed(f"the access file cannot be read ({type(exc).__name__})")
    else:
        access = with_keys(path.parent, _parsed(raw))
    if record:
        note_change(factory, access, by)
    return access


def _missing(factory: Factory, path: Path) -> Access:
    """No access file: a single operator's factory, unless access was enforced here before."""
    again = "IT restores it, or writes one with mode single_operator"
    last = last_change(factory)
    if last is not None and last.get("mode") == ENFORCED:
        return _closed(f"the access file was removed after access was enforced; {again}")
    if last is None and path.parent.is_dir():
        return _closed(f"its folder {ACCESS_DIR}/ is there without access.json; {again}")
    from kernel.team_access import access_of  # Rihmasto's own team mode (kernel/team.py, FR-PPL1)

    team = access_of(factory)
    if team is not None and (team.enforced or _team_recorded(factory)):
        return team
    if last is not None:
        return Access(SINGLE)
    signed = _signed_ledger(factory)
    if signed is not None:
        return _closed(f"the access file and the factory ledger's record of it are gone, while {signed}'s ledger "
                       f"holds writes signed by verified identities; {again}")
    return Access(SINGLE)


def _team_recorded(factory: Factory) -> bool:
    """A solo team file stands over verified writes only while the factory ledger records team mode's changes."""
    from kernel.team import RECORD

    ledger = factory.projects_dir / FACTORY_SCOPE / "ledger.jsonl"
    return ledger.exists() and bool(LedgerStore(ledger).of_kind(RECORD))


def _signed_ledger(factory: Factory) -> str | None:
    """A project whose ledger holds a record a verified identity signed (read once, then only what was
    appended since), or None."""
    try:
        dirs = sorted(d for d in factory.projects_dir.iterdir() if d.is_dir())
    except OSError:
        return None
    for d in dirs:
        ledger = d / "ledger.jsonl"
        try:
            size = ledger.stat().st_size
        except OSError:
            continue
        done, seen = _SCANNED.get(str(ledger), (0, False))
        if size < done:                                  # rewritten: read it whole again
            done, seen = 0, False
        if not seen and size > done:
            start = max(0, done - 64)                    # a record cut at the last read is read whole
            try:
                with open(ledger, "rb") as fh:
                    fh.seek(start)
                    seen = bool(_SIGNED.search(fh.read(size - start)))
            except OSError:
                continue
            _SCANNED[str(ledger)] = (size, seen)
        if seen:
            return d.name
    return None


def last_change(factory: Factory) -> dict | None:
    """The factory ledger's last ``access_changed`` record, or None (read again only when the ledger grew)."""
    ledger = factory.projects_dir / FACTORY_SCOPE / "ledger.jsonl"
    try:
        st = ledger.stat()
    except FileNotFoundError:
        return None
    key, stamp = str(ledger.resolve()), (st.st_size, st.st_mtime_ns)
    if key not in _LAST or _LAST[key][0] != stamp:
        found = LedgerStore(ledger).of_kind(CHANGED)
        _LAST[key] = (stamp, dict(found[-1]["event"]["payload"]) if found else None)
    return _LAST[key][1]


def note_change(factory: Factory, access: Access, by: str, ident: Identity | None = None) -> None:
    """Record in the factory ledger that the access rules changed: the file's sha256 (None while there is
    none) and the one before, the mode, whether it is valid, what the file claims about who changed it,
    its owner and modification time as the file system has them, and the surface and identity (``ident``,
    else the operating system's user) that noticed. Its lock is beside the factory ledger: the kernel
    never writes in the access file's folder."""
    def unchanged() -> bool:
        last = last_change(factory)
        if last is None:
            return access.sha256 is None and not access.enforced
        return last.get("sha256") == access.sha256 and last.get("mode") == access.mode and \
            last.get("keys_sha256") == access.keys_sha256

    if access.source == "team" or unchanged():     # team mode records its own changes (kernel/team.py)
        return
    from kernel.learn import factory_project

    project = factory_project(factory)
    with records_lock(lock_path(project.dir / CHANGED)):
        if unchanged():
            return
        previous = (last_change(factory) or {}).get("sha256")
        project.log(CHANGED, {"sha256": access.sha256, "previous": previous, "mode": access.mode,
                              "valid": access.error is None, "error": access.error, "claimed_by": access.changed_by,
                              **_on_disk(access_path(factory) if access.sha256 else None),
                              "keys_sha256": access.keys_sha256, "keys_error": access.keys_error,
                              "detected_by": by, "detected_as": ident.id if ident else _local_user()})


def _on_disk(path: Path | None) -> dict[str, Any]:
    """The file's owner and modification time, as the file system records them (None when unknown)."""
    try:
        modified = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).isoformat() if path else None
    except OSError:
        modified = None
    return {"file_owner": file_owner(path) if path else None, "file_modified": modified}


def _local_user() -> str | None:
    try:
        return LOCAL + os_user()
    except (OSError, KeyError):
        return None


# -- identities and grants -------------------------------------------------------------------------------

def _usable(access: Access) -> Access:
    if access.error is not None:
        raise AccessBroken(f"access is enforced, but {access.error}: every decision is refused until IT fixes it")
    return access


def identity(access: Access, ident_id: str, *, groups: tuple[str, ...] = (), email: str = "",
             expires: float | None = None) -> Identity:
    """The identity with its display name: the access file's, else the name the verified token carries.
    A token's name that looks like the name of someone the file lists under another identity (its
    ``skeleton``: case, spacing, compatibility forms, invisible characters and lookalike letters do not
    count), or that hides an invisible character or mixes lookalike scripts, is not taken as it is: the
    subject follows it, "Aino Example (stranger-sub)" (FR-ID4-AC-3, FR-ID5-AC-4)."""
    listed = access.people.get(ident_id)
    if listed:
        return Identity(ident_id, listed, tuple(groups), expires)
    subject = ident_id.rpartition("#")[2] or ident_id
    name = (email or subject).strip() or subject
    if disguised(name) or skeleton(name) in {skeleton(n) for i, n in access.people.items() if i != ident_id}:
        name = f"{visible(name) or subject} ({subject})"
    return Identity(ident_id, name, tuple(groups), expires)


def from_proxy(access: Access, headers: Headers, *, now: float | None = None) -> Identity:
    """The verified identity of a request IT's proxy forwarded: ``<issuer>#<subject>`` of the identity
    provider's signed token, with its name, groups and expiry (``kernel.access_tokens``). No token, one
    sent twice or one that does not verify is refused; so is an identity the file grants nothing."""
    proxy = _usable(access).proxy
    if proxy is None:
        raise AccessBroken("access is enforced, but the access file names no proxy")
    if access.keys_error is not None:
        raise AccessBroken(f"access is enforced, but {access.keys_error}: nobody can sign in until IT fixes it")
    try:
        who = signed_in(access, headers, now=now)
    except TokenRefused as exc:
        raise AccessRefused(f"this request did not come through the organisation's sign-in proxy with a valid "
                            f"token: {exc}") from None
    ident = identity(access, f"{proxy.issuer}#{who.subject}", groups=who.groups, email=who.name or "",
                     expires=who.expires + proxy.clock_skew)       # when the cockpit stops taking the token
    if not grants(access, ident):
        raise AccessRefused(f"{ident.id} is granted no persona in the access file; IT can bind one")
    return ident


def local_identity(access: Access) -> Identity:
    """``local:<os user>``, as the access file names it; refused when the file does not list it."""
    ident_id = LOCAL + os_user()
    if ident_id not in _usable(access).people:
        raise AccessRefused(f"access is enforced and {ident_id} is not in the access file; IT adds this "
                            "machine's user to it")
    return identity(access, ident_id)


def grants(access: Access, ident: Identity) -> list[Binding]:
    return [b for b in access.bindings if b.holds(ident)]


def personas(access: Access, ident: Identity, pid: str | None = None) -> list[str]:
    """The personas the identity holds on ``pid`` (None: on any project), in the usual order."""
    held = {b.persona for b in grants(access, ident) if b.covers(pid)}
    return [p for p in PERSONAS if p in held]


def sign(access: Access, ident: Identity | None, person: str | None, persona: str | None,
         pid: str | None) -> tuple[str, str]:
    """The one check (D-0016): may this identity decide as this persona on this project (``pid`` None:
    on any)? Returns the person and persona to record: the identity's name, never a typed one."""
    _usable(access)
    if ident is None:
        raise AccessRefused("access is enforced: a decision needs a verified identity (sign in through the "
                            "organisation's proxy, or run as a local user the access file names)")
    if person and person.strip() != ident.name:
        raise AccessRefused(f"the person is the signed-in identity, {ident.name}; {person.strip()!r} is not")
    if persona not in PERSONAS:
        raise AccessRefused(f"name the persona you act as: one of {', '.join(PERSONAS)}")
    if persona not in personas(access, ident, pid):
        where = "any project" if pid is None else pid
        held = ", ".join(personas(access, ident, pid)) or "none"
        raise AccessRefused(f"{ident.name} ({ident.id}) is not granted the {persona} persona on {where} "
                            f"(granted there: {held})")
    return ident.name, persona


def require(project: Project, person: str, persona: str) -> None:
    """The kernel's own check behind the surfaces' (``kernel.canon`` calls it on every decision,
    ``kernel.safestop`` on pause and resume): with access enforced, the write stands only when the
    identity signing it may make it. It trusts the signer this process set, no more."""
    access = load(project.factory)
    if access.enforced:
        sign(access, SIGNER.get(), person, persona, project.pid)


@contextlib.contextmanager
def signing(ident: Identity | None) -> Iterator[None]:
    """Carry out a write as ``ident``: its records name the identity beside the person. None: unsigned."""
    token = SIGNER.set(ident)
    try:
        yield
    finally:
        SIGNER.reset(token)


# -- what the surfaces show and the command line's signing ----------------------------------------------

def view(access: Access, ident: Identity | None) -> dict:
    """The access mode for the cockpit's header: the note, and in enforced mode who is signed in, the
    personas granted where, when the session ends (with the sign-in token) and where untrusted code runs."""
    if not access.enforced:
        return {"mode": SINGLE, "note": SINGLE_NOTE}
    out: dict[str, Any] = {"mode": ENFORCED, "error": access.error, "source": access.source}
    if ident is not None:
        from kernel.access_isolation import describe as isolation

        ends, where = _utc(ident.expires), isolation(access)
        through = f" through {access.proxy.preset}" if access.proxy and not ident.id.startswith("rihmasto:") else ""
        at = f"; the session ends with the sign-in token, at {ends[11:16]} UTC on {ends[:10]}" if ends else ""
        word = "team" if access.source == "team" else "enforced"
        out.update(identity=ident.id, name=ident.name, note=f"{word}: signed in as {ident.name}",
                   grants=[{"persona": b.persona, "scope": ALL if ALL in b.scope else list(b.scope)}
                           for b in grants(access, ident)], session_ends=ends,
                   detail=f"Signed in as {ident.name} ({ident.id}){through}{at}. {where[:1].upper()}{where[1:]}.")
    return out


def _utc(stamp: float | None) -> str | None:
    if stamp is None:
        return None
    return dt.datetime.fromtimestamp(stamp, dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def describe(access: Access) -> str:
    """One line for ``rihmasto status``: the mode, the cockpit's sign-in and where untrusted code runs."""
    if not access.enforced:
        return SINGLE_NOTE
    if access.error:
        return f"enforced, but {access.error}: every decision is refused"
    from kernel.access_isolation import describe as isolation

    proxy = access.proxy
    if access.source == "team":
        return f"team mode: decisions are signed by team members ({len(set(access.people.values()))} people, " \
               f"{len(access.bindings)} grants); {isolation(access)}"
    sign_in = f"{proxy.preset} tokens ({proxy.algorithm}), " if proxy else ""
    sign_in += f"but {access.keys_error}" if access.keys_error else f"{len(access.keys)} provider keys"
    return f"enforced: decisions are signed by verified identities ({len(access.people)} people, " \
           f"{len(access.bindings)} bindings); the cockpit's sign-in: {sign_in}; {isolation(access)}"


def request_digest(text: str) -> str:
    """The sha256 of a request's text as intake reads it (line endings as LF, ends trimmed)."""
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").strip().encode("utf-8")).hexdigest()


# The command line's signed writes that act on the factory, not on one project.
FACTORY_COMMANDS = ("new", "adopt", "embed create", "embed revoke", "signal log", "concept edit", "autonomy set")
REQUESTS = ("new", "intake")        # signed by --requested-by: a request in that person's name


def _cli_scopes(command: str, args: argparse.Namespace) -> list[str]:
    """Where a signed command acts. One that names no project (hooks, relay, connectors) acts on the
    factory; `pack withdraw|pin <pid>` acts on the project it names."""
    if command == "autonomy set" and args.project:
        return [args.project]
    if command == "pack" and args.pid in ("withdraw", "pin") and getattr(args, "words", None):
        return [args.words[0]]
    pid, project = getattr(args, "pid", None), getattr(args, "project", None)
    if command in FACTORY_COMMANDS or pid is None:
        return [FACTORY_SCOPE, *([project] if command in ("embed create", "hooks add") and project else [])]
    return [pid]


def _filed_in_cockpit(factory: Factory, args: argparse.Namespace) -> bool:
    """``intake`` carrying out a request a verified identity filed in the cockpit (the cockpit's own job):
    the project has no request yet, and its ledger's signed ``new_project`` record names this requester
    and this request's digest. Anything else that takes a request in someone's name is signed."""
    try:
        project = factory.project(args.pid)
        if not args.source_file or project.path("source.json").exists():
            return False
        digest = request_digest(Path(args.source_file).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        return False
    return any(p.get("action") == "new_project" and p.get("identity") and p.get("request_sha256") == digest
               and p.get("person") == args.requested_by
               for p in (r["event"]["payload"] for r in project.ledger().of_kind("cockpit_write")))


@contextlib.contextmanager
def cli_signing(factory: Factory, args: argparse.Namespace, command: str) -> Iterator[None]:
    """A command line write signed by a person, carried out as the local user (``local:<os user>``) when
    access is enforced: --person (``new`` and ``intake``: --requested-by) must be that user's name in the
    access file (it is taken when left out) and --persona (for a request: business_owner unless named)
    must be granted where the command acts. Single-operator mode changes nothing. Every command passes
    here and runs serving its factory: while access is enforced, the tests, products and Gnomon cells it
    starts go through IT's isolation runner, or are refused (``kernel.access_isolation``)."""
    from kernel.access_isolation import serving

    with serving(factory), _cli_signed(factory, args, command):
        yield


@contextlib.contextmanager
def _cli_signed(factory: Factory, args: argparse.Namespace, command: str) -> Iterator[None]:
    key = "requested_by" if command in REQUESTS else "person"
    if not hasattr(args, key):
        yield
        return
    access = load(factory, record=True, by="the command line")
    if not access.enforced or (command == "intake" and access.error is None and _filed_in_cockpit(factory, args)):
        yield
        return
    ident = local_identity(access)
    persona = getattr(args, "persona", None) or ("business_owner" if key == "requested_by" else None)
    for pid in _cli_scopes(command, args):
        name, persona = sign(access, ident, getattr(args, key), persona, pid)
    setattr(args, key, name)
    with signing(ident):
        yield
