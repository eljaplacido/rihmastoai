"""The cockpit's routes for Shape it in chat (kernel/shape.py) and Models setup (kernel/models_setup.py).

Every write is signed by a person and persona as the other write routes are (with access enforced, a persona
granted on the factory), and recorded in the factory's ledger by the kernel. Rihma's answer runs beside the
request, in a thread, so a slow model never holds the write lock: the conversation says it is pending, and
the page reads it again until the answer is in. Testing a model's endpoint records nothing.
"""

from __future__ import annotations

import threading
from typing import Any

from kernel import models_setup as kmodels
from kernel import shape as kshape
from kernel.learn import FACTORY_PID

SID = r"(?P<sid>SH-\d{3,6})"
ROLE = r"(?P<role>[a-z][a-z_]{0,31})"
ROUTES = [
    ("GET", r"/api/shape", "get_shapes"),
    ("GET", rf"/api/shape/{SID}", "get_shape"),
    ("POST", r"/api/shape", "post_shape"),
    ("POST", rf"/api/shape/{SID}/say", "post_shape_say"),
    ("POST", rf"/api/shape/{SID}/attach", "post_shape_attach"),
    ("PUT", rf"/api/shape/{SID}/draft", "put_shape_draft"),
    ("POST", rf"/api/shape/{SID}/create", "post_shape_create"),
    ("GET", r"/api/models", "get_models"),
    ("PUT", rf"/api/models/{ROLE}", "put_model"),
    ("POST", rf"/api/models/{ROLE}/test", "post_model_test"),
    ("POST", rf"/api/models/{ROLE}/remove", "post_model_remove"),
]
# Testing an endpoint records nothing and may wait on the network: it runs outside the write lock.
UNLOCKED = {"post_model_test"}
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def _text(body: dict[str, Any], key: str, *, required: bool = False, limit: int = 20000) -> str:
    return str(_server()._text(body, key, required=required, limit=limit))


class ChatRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory`` and ``_who``."""

    server: Any
    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _chat_signer(self, body: dict[str, Any]) -> tuple[str, str]:
        person, persona = self._who(body, FACTORY_PID)
        _server()._require_person(person, persona)
        return person, persona

    def _chat_conv(self, sid: str) -> dict[str, Any]:
        try:
            return kshape.get(self.factory, sid)
        except KeyError:
            raise _error(404, f"no conversation {sid}") from None

    def _chat_turn(self, conv: dict[str, Any]) -> dict[str, Any]:
        """Rihma's turn: at once when there is no model (the chat says so), else in a thread."""
        if not conv.get("pending"):
            return conv
        model = getattr(self.server, "shape_model", None)
        if model is None:
            return kshape.answer(self.factory, conv["id"], None)
        thread = threading.Thread(target=kshape.answer, args=(self.factory, conv["id"], model),
                                  name=f"shape-{conv['id']}", daemon=True)
        thread.start()
        return conv

    def _chat_out(self, conv: dict[str, Any]) -> dict[str, Any]:
        return {"shape": kshape.view(conv), "model": getattr(self.server, "shape_model", None) is not None}

    # reads

    def get_shapes(self, **_: object) -> Reply:
        return 200, {"conversations": kshape.conversations(self.factory),
                     "model": getattr(self.server, "shape_model", None) is not None}

    def get_shape(self, sid: str, **_: object) -> Reply:
        return 200, self._chat_out(self._chat_conv(sid))

    # writes

    def _chat_attach(self, sid: str, given: Any, person: str, persona: str, pending: bool) -> dict[str, Any]:
        if not isinstance(given, dict):
            raise _error(400, "attach is {path} or {name, text} or {name, data_base64}")
        return kshape.attach(self.factory, sid, person=person, persona=persona, pending=pending,
                             path=_text(given, "path", limit=2000) or None, name=_text(given, "name", limit=200) or None,
                             text=given.get("text") if isinstance(given.get("text"), str) else None,
                             data_base64=_text(given, "data_base64", limit=1_400_000) or None)

    def post_shape(self, body: dict[str, Any], **_: object) -> Reply:
        """Open a conversation, with a first message and an attachment when given; Rihma answers them."""
        person, persona = self._chat_signer(body)
        text = _text(body, "text", limit=kshape.MAX_MESSAGE)
        conv = kshape.start(self.factory, person=person, persona=persona, title=_text(body, "title", limit=200))
        if body.get("attach"):
            conv = self._chat_attach(conv["id"], body["attach"], person, persona, pending=not text)
        if text:
            conv = kshape.say(self.factory, conv["id"], text, person=person, persona=persona)
        return 201, self._chat_out(self._chat_turn(conv))

    def post_shape_say(self, sid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._chat_signer(body)
        self._chat_conv(sid)
        conv = kshape.say(self.factory, sid, _text(body, "text", required=True, limit=kshape.MAX_MESSAGE),
                          person=person, persona=persona)
        return 200, self._chat_out(self._chat_turn(conv))

    def post_shape_attach(self, sid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._chat_signer(body)
        self._chat_conv(sid)
        conv = self._chat_attach(sid, body.get("attach") or body, person, persona, pending=True)
        return 200, self._chat_out(self._chat_turn(conv))

    def put_shape_draft(self, sid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._chat_signer(body)
        self._chat_conv(sid)
        draft = body.get("draft")
        if not isinstance(draft, dict):
            raise _error(400, "draft is an object of the fields you changed")
        return 200, self._chat_out(kshape.edit_draft(self.factory, sid, draft, person=person, persona=persona))

    def post_shape_create(self, sid: str, body: dict[str, Any], **_: object) -> Reply:
        """The project from the draft: created as New project creates one, its intake a job; the conversation
        is kept with it as its request."""
        person, persona = self._chat_signer(body)
        conv = self._chat_conv(sid)
        kshape.ready_to_create(conv)
        chose = kshape.choice(conv, profile=_text(body, "profile", limit=64) or None,
                              mode=_text(body, "mode", limit=32) or None, maturity=_text(body, "maturity", limit=32) or None)
        status, out = getattr(self, "post_project")({**chose, "title": kshape.title_of(conv), "source": kshape.brief(conv),
                                                     "requested_by": person, "persona": persona})
        project = self.factory.project(out["project"]["id"])
        conv = kshape.mark_created(self.factory, sid, project, person=person, persona=persona, chose=chose)
        return status, {**out, **self._chat_out(conv)}

    # models

    def get_models(self, **_: object) -> Reply:
        return 200, {**kmodels.models_view(), "chat_model": getattr(self.server, "shape_model", None) is not None}

    def _chat_refresh(self) -> None:
        """A chat model that compiles its lane (kernel.models_setup.LaneModel) takes the new routing at once."""
        refresh = getattr(getattr(self.server, "shape_model", None), "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except (OSError, ValueError, RuntimeError):   # the next message compiles it again, and says why if not
                pass

    def put_model(self, role: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._chat_signer(body)
        view = kmodels.set_role(self.factory, role, base_url=_text(body, "base_url", required=True, limit=500),
                                model=_text(body, "model", required=True, limit=200), person=person, persona=persona,
                                family=_text(body, "family", limit=64) or None,
                                key_env=_text(body, "key_env", limit=64) or None, key=_text(body, "key", limit=4000) or None,
                                keep_fallback=body.get("keep_fallback") is not False,
                                private=body.get("private") is True)
        self._chat_refresh()
        return 200, {"role": view}

    def post_model_test(self, role: str, body: dict[str, Any], **_: object) -> Reply:
        self._chat_signer(body)
        return 200, {"test": kmodels.probe_role(role)}

    def post_model_remove(self, role: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._chat_signer(body)
        view = kmodels.remove_role(self.factory, role, person=person, persona=persona)
        self._chat_refresh()
        return 200, {"role": view}
