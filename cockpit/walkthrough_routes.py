"""The cockpit's routes for walkthroughs in Ask Rihma (kernel/walkthrough.py, FR-WLK1).

Starting, replying and cancelling are signed by a person and persona as every write route is (with access
enforced, a persona granted on the factory, and a walkthrough answers only the person who started it); they
write only the walkthrough's own file and its ledger records, under their own locks, so they run outside the
write lock (a folder's scan or a model's Test may take a while). Confirming a proposal calls the cockpit's own
route for it, in this same request and under the write lock: Adopt is ``post_adopt``, Create is
``post_project``, Set the role is ``put_model``, Set the kind is ``put_settings`` and Open Shape it in chat is
``post_shape``, each with its module check, signing, access and isolation checks, so a walkthrough takes no
path the cockpit's own buttons do not. Reading a walkthrough shows the job it waits on, with the progress the
job printed; it writes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel import modules as kmodules
from kernel import walkthrough as kwalk
from kernel.learn import FACTORY_PID
from kernel.walkthrough_flows import progress_in_log, progress_of

WID = r"(?P<wid>WT-\d{3,6})"
ROUTES = [
    ("GET", r"/api/walkthroughs", "get_walkthroughs"),
    ("GET", rf"/api/walkthroughs/{WID}", "get_walkthrough"),
    ("POST", r"/api/walkthroughs", "post_walkthrough"),
    ("POST", rf"/api/walkthroughs/{WID}/reply", "post_walkthrough_reply"),
    ("POST", rf"/api/walkthroughs/{WID}/confirm", "post_walkthrough_confirm"),
    ("POST", rf"/api/walkthroughs/{WID}/cancel", "post_walkthrough_cancel"),
]
UNLOCKED = {"post_walkthrough", "post_walkthrough_reply", "post_walkthrough_cancel"}
# The cockpit route each proposal is carried out by: its module check is the route's own.
CARRIED_BY = {"adopt": "post_adopt", "new_project": "post_project", "set_model": "put_model",
              "set_kind": "put_settings", "shape": "post_shape"}
READ_PROMPT = """A person is answering a question in a step-by-step walkthrough of a software factory's cockpit.
Their reply did not match any offered option by rule. Say which one option they mean, or none. Never choose
for them: when the reply is unclear, answer none.

Options (id: label):
{options}

Their reply:
<<<
{reply}
>>>

Answer with JSON only: {{"option": "<an id from the list, or none>"}}
"""
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _text(body: dict[str, Any], key: str, *, limit: int = 2000) -> str:
    return str(_server()._text(body, key, limit=limit))


class WalkRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``access``, ``_who`` and the routes a
    proposal is carried out by."""

    server: Any
    factory: Any
    access: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _walk_signer(self, body: dict[str, Any]) -> tuple[str, str]:
        person, persona = self._who(body, FACTORY_PID)
        _server()._require_person(person, persona)
        return person, persona

    def _walk(self, wid: str) -> dict[str, Any]:
        try:
            return kwalk.get(self.factory, wid)
        except KeyError:
            raise _server().ApiError(404, f"no walkthrough {wid}") from None

    def _walk_job(self, jid: Any) -> dict[str, Any] | None:
        if not jid:
            return None
        job = next((j for j in list(self.server.jobs) if j["id"] == jid), None)
        if job is None:
            return {"id": jid, "state": "lost", "log_tail": ["the cockpit was restarted while the job ran"]}
        return dict(self.server.job_view(job)) | {"progress_lines": progress_in_log(Path(job["log"]))}

    def _walk_out(self, w: dict[str, Any], **extra: Any) -> dict[str, Any]:
        out = kwalk.view(w)
        job = self._walk_job(out.get("job")) if out["awaiting"]["kind"] == "job" else None
        if job is not None:
            out["job_view"] = {"id": job.get("id"), "state": job.get("state"), "started": job.get("started"),
                               "progress": progress_of(job)}
        return {"walkthrough": out, **{k: v for k, v in extra.items() if v}}

    def _walk_reader(self, w: dict[str, Any] | None) -> kwalk.Reader | None:
        """The assistant's model reading a free-text reply into one of the offered options, or None: no model,
        the assistant module off, or a confidential walkthrough while the assistant's model is hosted."""
        from kernel import confidential
        from kernel.model import extract_json

        model = getattr(self.server, "assistant_model", None)
        if model is None or not kmodules.is_on(self.factory, "assistant"):
            return None
        if ((w or {}).get("data") or {}).get("confidential") and confidential.refusal(["assistant"]):
            return None

        def read(reply: str, options: list[dict[str, Any]]) -> str | None:
            listed = "\n".join(f"- {o['id']}: {o['label']}" for o in options)
            got = extract_json(model.ask(READ_PROMPT.format(options=listed, reply=reply), role="assistant"))
            return str(got.get("option")) if isinstance(got, dict) else None

        return read

    def _walk_runner(self, person: str, persona: str) -> kwalk.Runner:
        api = self

        def run(prop: dict[str, Any]) -> dict[str, Any]:
            a, who = dict(prop.get("args") or {}), {"person": person, "persona": persona}
            route = CARRIED_BY.get(str(prop.get("action")))
            if route is None:
                raise kwalk.WalkRefused(f"no such proposal: {prop.get('action')}")
            pid = a.get("project") if route == "put_settings" else None
            kmodules.require_route(api.factory, route, pid)
            body = {k: v for k, v in a.items() if v is not None}
            try:
                if route == "post_adopt":
                    return dict(getattr(api, route)(body={**body, **who})[1])
                if route == "post_project":
                    return dict(getattr(api, route)(body={**body, "requested_by": person, "persona": persona})[1])
                if route == "put_model":
                    return dict(getattr(api, route)(role=a["role"], body={**body, **who})[1])
                if route == "put_settings":
                    return dict(getattr(api, route)(pid=pid, body={"kind": a["kind"], **who,
                                                                    "reason": "chosen in the walkthrough"})[1])
                return dict(getattr(api, route)(body={"text": a["text"], **who})[1])
            except _server().ApiError as exc:
                raise kwalk.WalkRefused(exc.message) from None

        return run

    # reads

    def get_walkthroughs(self, query: dict[str, Any], **_: object) -> Reply:
        """The walkthroughs on offer, and the asking person's own one that is going, if any."""
        person = str(query.get("person") or "").strip()
        going = kwalk.mine(self.factory, person) if person else None
        return 200, {"walkthroughs": kwalk.catalogue(), "yours": kwalk.view(going) if going else None,
                     "model": self._walk_reader(None) is not None}

    def get_walkthrough(self, wid: str, **_: object) -> Reply:
        return 200, self._walk_out(self._walk(wid))

    # writes

    def post_walkthrough(self, body: dict[str, Any], **_: object) -> Reply:
        """Start a walkthrough, or resume the person's one of that name."""
        person, persona = self._walk_signer(body)
        name = _text(body, "name", limit=32)
        try:
            w = kwalk.start(self.factory, name, person=person, persona=persona, said=_text(body, "said"),
                            replace=body.get("replace") is True, reader=self._walk_reader(None))
        except kwalk.WalkRefused as exc:
            raise _server().ApiError(409 if "is going" in str(exc) else 400, str(exc)) from None
        return 201, self._walk_out(w)

    def post_walkthrough_reply(self, wid: str, body: dict[str, Any], **_: object) -> Reply:
        """A reply: typed text, a button's choice, the files unticked in the full map, or ``job: true`` once the
        job it waits on ended (read here from the cockpit's own jobs, never from the page)."""
        person, persona = self._walk_signer(body)
        w = self._walk(wid)
        exclude = body.get("exclude")
        if exclude is not None:
            exclude = getattr(self, "_excludes")({"exclude": exclude})
        job = self._walk_job((w.get("data") or {}).get("job")) if body.get("job") is True else None
        if body.get("job") is True and job is None:
            raise _server().ApiError(400, "this walkthrough waits on no job")
        try:
            out = kwalk.reply(self.factory, wid, person=person, persona=persona, text=_text(body, "text"),
                              choice=_text(body, "choice", limit=200) or None, exclude=exclude, job=job,
                              reader=self._walk_reader(w), enforced=bool(self.access.enforced))
        except kwalk.WalkRefused as exc:
            raise _server().ApiError(400, str(exc)) from None
        return 200, self._walk_out(out, resumed=out.get("resumed"), switched_from=out.get("switched_from"))

    def post_walkthrough_confirm(self, wid: str, body: dict[str, Any], **_: object) -> Reply:
        """Carry out the proposal the walkthrough waits on, through the cockpit's own route for it."""
        person, persona = self._walk_signer(body)
        self._walk(wid)
        try:
            out = kwalk.confirm(self.factory, wid, person=person, persona=persona,
                                run=self._walk_runner(person, persona), enforced=bool(self.access.enforced))
        except kwalk.WalkRefused as exc:
            raise _server().ApiError(400, str(exc)) from None
        return 200, self._walk_out(out, refused=out.get("refused"), resumed=out.get("resumed"))

    def post_walkthrough_cancel(self, wid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._walk_signer(body)
        self._walk(wid)
        out = kwalk.cancel(self.factory, wid, person=person, persona=persona, enforced=bool(self.access.enforced))
        return 200, self._walk_out(out, resumed=out.get("resumed"))
