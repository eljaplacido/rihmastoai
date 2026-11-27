"""The cockpit's routes for choosing a folder or a file by browsing (FR-PICK1; docs/guides/inputs.md).

- ``GET /api/pick/places``: where browsing starts (recent folders, the roots, the home folder, the drives), each
  with whether the cockpit may read it, and whether Browse… can open the computer's own dialog for this request.
- ``GET /api/pick/list?path=...&files=0|1``: one folder's subfolders (and files), with git and project badges and
  a readable flag with the reason (kernel/pick.py). A system folder or a folder of keys is never listed; outside
  the allowed folders a single operator sees subfolder names only, and enforced access refuses it.
- ``POST /api/pick/native``: the computer's own dialog on the cockpit's machine (kernel/pick_native.py), only
  for the loopback browser of a single operator's cockpit; else 409 "use the folder browser". A page reached
  through an SSH tunnel looks like the loopback page, so the page names the machine the dialog opened on and
  offers Browse here instead while it is open.
- ``POST /api/pick/native/cancel``: closes the dialog open now (from anywhere), which then answers cancelled.
- ``GET /api/pick/list?...&q=text``: only the entries whose names hold the text, searched before the cap.
- ``POST /api/pick/recent``: a folder chosen, kept with this person's recent folders (beside the walkthroughs',
  in the home, outside every ledger), after source_guard says the cockpit may read it.

The reads are signed like the writes (the person and a persona that may read a folder); none records anything.
"""

from __future__ import annotations

import socket
from typing import Any

from kernel import pick as kpick
from kernel import pick_native as knative
from kernel import source_guard as ksource
from kernel.learn import FACTORY_PID

ROUTES = [
    ("GET", r"/api/pick/places", "get_pick_places"),
    ("GET", r"/api/pick/list", "get_pick_list"),
    ("POST", r"/api/pick/native", "post_pick_native"),
    ("POST", r"/api/pick/native/cancel", "post_pick_cancel"),
    ("POST", r"/api/pick/recent", "post_pick_recent"),
]
# A dialog waits on the person for minutes: it never holds the write lock. Choosing records nothing.
UNLOCKED = {"post_pick_native", "post_pick_cancel"}
Reply = tuple[int, dict[str, Any]]
REMOTE = ("use the folder browser: the computer's own dialog opens only for the browser on the cockpit's machine "
          "of a single operator's cockpit")


def _server() -> Any:
    from cockpit import server

    return server


class PickRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server``, ``access``, ``request_origin`` and ``_sign``."""

    factory: Any
    server: Any
    access: Any
    request_origin: str
    forwarded: bool

    def _sign(self, person: str, persona: str, pid: str | None) -> tuple[str, str]:  # pragma: no cover
        raise NotImplementedError

    def _pick_who(self, given: dict[str, Any]) -> tuple[str, str]:
        srv = _server()
        persona = srv._text(given, "persona", limit=64)
        if persona not in srv.PERSONAS:
            raise srv.ApiError(400, f"persona must be one of {', '.join(srv.PERSONAS)}")
        return self._sign(srv._text(given, "person", limit=200), persona, FACTORY_PID)

    def _at_the_machine(self) -> bool:
        """Whether this request comes from the browser on the cockpit's own machine, for a single operator."""
        return (not self.access.enforced and not getattr(self, "forwarded", False)
                and getattr(self, "request_origin", "") == self.server.origin)

    def _native(self) -> dict[str, Any]:
        tool = knative.tool()
        here = self._at_the_machine()
        why = None if here and tool else REMOTE if not here else "no folder dialog can be opened on this machine"
        return {"available": bool(here and tool), "tool": tool if here else None, "why": why,
                "busy": knative.busy(), "platform": kpick.platform(), "host": socket.gethostname() if here else None}

    def get_pick_places(self, query: dict[str, Any], **_: object) -> Reply:
        person, _persona = self._pick_who(query)
        return 200, {"places": kpick.places(self.factory, person), "native": self._native(),
                     "enforced": bool(self.access.enforced)}

    def get_pick_list(self, query: dict[str, Any], **_: object) -> Reply:
        srv = _server()
        _person, persona = self._pick_who(query)
        try:
            out = kpick.listing(self.factory, query.get("path"), persona=persona, files=query.get("files") == "1",
                                enforced=bool(self.access.enforced), q=str(query.get("q") or "")[:200])
        except ksource.SourceRefused as exc:
            raise srv.ApiError(403, str(exc)) from None
        return 200, {"folder": out}

    def post_pick_native(self, body: dict[str, Any], **_: object) -> Reply:
        srv = _server()
        person, persona = self._pick_who(body)
        srv._require_person(person, persona)
        kind = srv._text(body, "kind", limit=16) or "folder"
        if kind not in knative.KINDS:
            raise srv.ApiError(400, f"kind is one of {', '.join(knative.KINDS)}")
        if not self._at_the_machine():
            raise srv.ApiError(409, REMOTE)
        try:
            got = knative.choose(kind, srv._text(body, "title", limit=200), srv._text(body, "start", limit=2000))
        except knative.NativeBusy as exc:
            raise srv.ApiError(409, str(exc)) from None
        except knative.NativeUnavailable as exc:
            raise srv.ApiError(501, str(exc)) from None
        if got is None:
            return 200, {"cancelled": True}
        return 200, {"picked": kpick.describe(self.factory, got, persona=persona,
                                              enforced=bool(self.access.enforced))}

    def post_pick_cancel(self, body: dict[str, Any], **_: object) -> Reply:
        """Close the dialog open on the cockpit's machine: from anywhere, since a page reached through an SSH
        tunnel looks like the loopback page and may have opened it where nobody sits."""
        srv = _server()
        person, persona = self._pick_who(body)
        srv._require_person(person, persona)
        return 200, {"cancelled": knative.cancel()}

    def post_pick_recent(self, body: dict[str, Any], **_: object) -> Reply:
        from kernel import walkthrough as wk

        srv = _server()
        person, persona = self._pick_who(body)
        srv._require_person(person, persona)
        try:
            path = ksource.check_folder(srv._text(body, "path", required=True, limit=2000), persona,
                                        self.factory.home)
        except ksource.SourceRefused as exc:
            raise srv.ApiError(403, str(exc)) from None
        wk.remember(self.factory, person, str(path))
        return 200, {"recent": wk.recent(self.factory, person)}
