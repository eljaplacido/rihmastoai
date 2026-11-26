"""`rihmasto access ...`: IT checks its access setup before people sign in (D-0016, FR-ID1, FR-ID2).

- ``rihmasto access check [--token-file F]`` reads the access file and the provider's key file as the
  cockpit would, says where untrusted code would run, and, given a token saved from the sign-in proxy (a
  test user's), verifies it offline and shows the identity, name, groups and personas it would sign in
  with. It writes nothing and exits 2 when something would be refused.
- ``rihmasto access keys <kid>=<file.pem> ...`` prints a JWKS for public keys in PEM form (AWS ALB
  publishes one per key id), for the access folder's key file.

Both are read-only and sign nothing; a token file is read, never kept or printed back.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import access as kaccess
from kernel import access_isolation as isolation
from kernel import team_cli
from kernel.jwt_verify import jwk_from_pem
from kernel.store import Factory

Handler = Callable[[Factory, argparse.Namespace], int]


class _Forwarded:
    """The one header a saved token arrives in, as the sign-in proxy would forward it."""

    def __init__(self, name: str, value: str) -> None:
        self.name, self.value = name.lower(), value

    def get_all(self, name: str, failobj: Any = None, /) -> Any:
        return [self.value] if name.lower() == self.name else failobj


def add_parsers(sub: Any) -> None:
    """`rihmasto access check|keys`, as the command line's parser adds it."""
    cmds = sub.add_parser("access", help="IT checks the access setup, read only (kernel/access.py)").add_subparsers(
        dest="sub", required=True)
    p = cmds.add_parser("check", help="the access file, the provider's keys, the isolation runner, and a sample token")
    p.add_argument("--token-file", help="a token saved from the sign-in proxy, verified offline as the cockpit would")
    p = cmds.add_parser("keys", help="print a JWKS for the provider's public keys in PEM form")
    p.add_argument("pairs", nargs="+", metavar="KID=FILE.pem")
    team_cli.add_parsers(cmds)          # solo and team mode (kernel/team.py, FR-PPL1)


def check(factory: Factory, token_file: str | None = None) -> dict:
    """What the cockpit would make of the access setup now, and of a saved token: ``ready`` says whether
    nothing in it would be refused."""
    access = kaccess.load(factory)
    out: dict[str, Any] = {"mode": access.mode, "file": str(kaccess.access_path(factory)),
                           "valid": access.error is None, "error": access.error, "status": kaccess.describe(access)}
    if not access.enforced:
        return out | {"ready": access.error is None}
    proxy = access.proxy
    if proxy is not None:
        out["sign_in"] = {"preset": proxy.preset, "issuer": proxy.issuer, "audience": proxy.audience,
                          "algorithm": proxy.algorithm, "token_header": proxy.token_header, "key_file": proxy.keys,
                          "keys": sorted(access.keys), "keys_error": access.keys_error,
                          "claims": {"subject": proxy.subject_claim, "name": proxy.name_claim,
                                     "groups": proxy.groups_claim}}
    work = {what: isolation.unusable(access, what) for what in (isolation.SUITE, isolation.PRODUCT, isolation.CELL)}
    out["isolation"] = {"runner": isolation.describe(access), "refused": {k: v for k, v in work.items() if v}}
    # Ready needs the tests and the cells to have a runner; a product may take a docker road instead.
    ready = access.error is None and access.keys_error is None and not (work[isolation.SUITE] or work[isolation.CELL])
    if token_file and proxy is not None:
        raw = Path(token_file).read_text(encoding="utf-8").strip()
        given = f"Bearer {raw}" if proxy.token_header.lower() == "authorization" and " " not in raw else raw
        try:
            ident = kaccess.from_proxy(access, _Forwarded(proxy.token_header, given))
        except kaccess.AccessRefused as exc:
            out["token"] = {"refused": str(exc)}
            ready = False
        else:
            out["token"] = {"identity": ident.id, "name": ident.name, "groups": list(ident.groups),
                            "expires": kaccess.view(access, ident)["session_ends"],
                            "grants": kaccess.view(access, ident)["grants"]}
    return out | {"ready": ready}


def keys(pairs: list[str]) -> dict:
    """A JWKS for ``<kid>=<file.pem>`` pairs."""
    out = []
    for pair in pairs:
        kid, sep, path = pair.partition("=")
        if not sep or not kid or not path:
            raise ValueError(f"{pair!r} is not <kid>=<file.pem>")
        out.append(jwk_from_pem(Path(path).read_text(encoding="ascii"), kid))
    return {"keys": out}


def handlers(show: Callable[[Any], None]) -> dict[str, Handler]:
    """The `rihmasto access` handlers: ``check`` exits 2 when something would be refused."""
    def run_check(f: Factory, a: argparse.Namespace) -> int:
        report = check(f, a.token_file)
        show(report)
        return 0 if report["ready"] else 2

    def run_keys(_: Factory, a: argparse.Namespace) -> int:
        show(keys(a.pairs))
        return 0

    return {"access check": run_check, "access keys": run_keys, **team_cli.handlers(show)}
