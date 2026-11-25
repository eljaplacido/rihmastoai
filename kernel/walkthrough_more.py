"""Start from a new idea, set up a model, and the Get started tour (kernel/walkthrough.py, FR-WLK1).

New idea: the person's idea in a sentence or two, then Shape it in chat with that sentence carried over (the
conversation opens when they confirm), or a quick start: a title, one paragraph, the maturity, "Create the
project" (the cockpit's own New project), its intake waited on and the first questions as buttons.

Set up a model: each role with its readiness (Models setup), a preset (a server on this machine, a hosted
OpenAI-compatible provider, or a host on your own network), the URL, the model and the NAME of the variable
that holds the key (a key itself is never typed into the chat: one that looks like a key is not kept), "Set
the <role>" (the cockpit's own Models setup), then Test, with the latency or the error said in the chat.

Get started: five stops (Home, the Inbox, a project with What's next, Project settings, Ask Rihma itself),
each with Take me there, and Next and Back.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import walkthrough as wk
from kernel import walkthrough_flows as wf
from kernel.walkthrough_adopt import Documents

KINDS = (("local", "A server on this machine", "llama.cpp, Ollama or vLLM, reached on 127.0.0.1"),
         ("hosted", "A hosted OpenAI-compatible provider", "OpenAI, OpenRouter or another, with an API key"),
         ("network", "On my own network", "a GPU box on a tailnet or a VPN; confidential projects may use it"))
PRESET_KIND = {"llama_cpp": "local", "ollama": "local", "vllm": "local", "opencode_go": "hosted", "openai": "hosted",
               "openrouter": "hosted"}
READY_WORD = {"ready": "answers", "configured": "set, with its key", "no_key": "has no key",
              "unreachable": "does not answer", "unknown": "not checked"}
LOOKS_LIKE_KEY = re.compile(r"^(sk-|sk_|gsk_|xai-|AIza)|[a-z].*[0-9].*[A-Z]|[A-Z].*[0-9].*[a-z]")


class NewIdea(wf.Flow):
    name, label, control = "new_idea", "Start from a new idea", "walk_new_idea"
    about = "your idea in your own words: shaped in chat with Rihma, or a quick start"
    intro = "Let's start from your idea. Nothing is created until you confirm it."
    first = "idea"
    steps = ("idea", "how", "title", "need", "maturity", "confirm", "intake", "done")

    def ask_idea(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Tell me the idea in a sentence or two, in your own words: who it is for and what it solves.",
                       input={"kind": "text", "placeholder": "Our team keeps losing track of ..."})

    def take_idea(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        text = str(reply.get("text") or "").strip()
        if not text:
            return None
        ctx.data["idea"] = text
        return "how"

    def ask_how(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("How do you want to go on?", options=[
            {"id": "shape", "label": "Shape it in chat (recommended)", "keys": "chat conversation",
             "hint": "Rihma asks what is missing and keeps a draft brief you edit"},
            {"id": "quick", "label": "Quick start", "keys": "fast form",
             "hint": "a title, one paragraph and how mature"}])

    def take_how(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = wf.pick(ctx, reply, wk.offered(ctx.w))
        return {"shape": "handover", "quick": "title"}.get(str(got)) if got else None

    def ask_handover(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Your first sentence is carried over to the conversation, and Rihma answers it there.",
                       proposal={"action": "shape", "label": "Open Shape it in chat",
                                 "lines": [f"“{ctx.data['idea'][:300]}”"], "args": {"text": ctx.data["idea"]}})

    def done_handover(self, ctx: wk.Ctx, prop: dict[str, Any], result: dict[str, Any]) -> str:
        ctx.data["shape"] = ((result.get("shape") or {}).get("id"))
        return "done"

    def ask_title(self, ctx: wk.Ctx) -> dict[str, Any]:
        ctx.data.setdefault("title", " ".join(ctx.data["idea"].split()[:6]).rstrip(".,;:").capitalize())
        return super().ask_title(ctx)

    def take_title(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        return "need" if super().take_title(ctx, reply) else None

    def ask_need(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Describe the need in one paragraph: who it is for, the problem, and what a first version "
                       "should do.", options=[{"id": "same", "label": "Use what I said"}],
                       input={"kind": "text", "placeholder": "One paragraph"})

    def take_need(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        text = ctx.data["idea"] if reply.get("choice") == "same" else str(reply.get("text") or "").strip()
        if not text:
            return None
        ctx.data["need"] = text
        return "maturity"

    def _maturities(self) -> list[dict[str, Any]]:
        from kernel.intake import MATURITY_MEANING

        return [{"id": k, "label": k.capitalize(), "hint": v} for k, v in MATURITY_MEANING.items()]

    def ask_maturity(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("How far should it go?", options=self._maturities())

    def take_maturity(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = wf.pick(ctx, reply, self._maturities())
        if got is None:
            return None
        ctx.data["maturity"] = got
        return "confirm"

    def ask_confirm(self, ctx: wk.Ctx) -> dict[str, Any]:
        d = ctx.data
        return ctx.say("Ready. Nothing has been done yet. Creating the project starts its intake as a job.", proposal={
            "action": "new_project", "label": "Create the project",
            "lines": [f"Title: {d['title']}", f"Maturity: {d['maturity']}", f"Need: {d['need'][:300]}"],
            "args": {"title": d["title"], "source": d["need"], "maturity": d["maturity"]}})

    done_confirm = Documents.done_confirm          # the project made: its intake waited on, as from documents
    ask_intake = Documents.ask_intake
    take_intake = Documents.take_intake

    def ask_done(self, ctx: wk.Ctx) -> dict[str, Any]:
        if ctx.data.get("shape"):
            sid = ctx.data["shape"]
            return ctx.say(f"The conversation {sid} is open: go on there.", final=True,
                           links=[{"label": "Open the conversation", "route": f"#/shape/{sid}"}], go=f"#/shape/{sid}")
        pid = ctx.data.get("project")
        return ctx.say("Done.", final=True, links=[wf.open_project(pid)] if pid else None)


class Model(wf.Flow):
    name, label, control = "model", "Set up a model", "walk_model"
    about = "point a role at a model on this machine, your network or a hosted provider, and test it"
    intro = "Let's point one of Rihmasto's roles at a model. Nothing changes until you press Set."
    first = "role"
    steps = ("role", "kind", "url", "model", "key", "confirm", "test", "done")

    def untick(self, ctx: wk.Ctx, exclude: list[str]) -> None:
        ctx.say("There is no folder in this walkthrough.")

    def ask_role(self, ctx: wk.Ctx) -> dict[str, Any]:
        from kernel.models_setup import models_view

        roles = models_view()["roles"]
        lines = [f"{r['label']}: {r['model']} at {r['host'] or '?'}, {'local' if r['local'] else 'hosted'}, "
                 f"{READY_WORD.get(r['readiness']['state'], r['readiness']['state'])}" for r in roles]
        return ctx.say("Each role and its model now:\n" + "\n".join("- " + x for x in lines)
                       + "\nWhich role do you want to set?",
                       options=[{"id": r["role"], "label": r["label"], "hint": r["purpose"]} for r in roles])

    def take_role(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = wf.pick(ctx, reply, wk.offered(ctx.w))
        if got is None:
            return None
        ctx.data["role"] = got
        return "kind"

    def ask_kind(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Where does the model run?",
                       options=[{"id": k, "label": label, "hint": hint} for k, label, hint in KINDS])

    def take_kind(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = wf.pick(ctx, reply, [{"id": k, "label": label, "keys": hint} for k, label, hint in KINDS])
        if got is None:
            return None
        ctx.data["kind"] = got
        return "url"

    def _presets(self, ctx: wk.Ctx) -> list[dict[str, Any]]:
        from kernel.models_setup import PRESETS

        return [p for p in PRESETS if PRESET_KIND.get(p["id"]) == ctx.data.get("kind")]

    def ask_url(self, ctx: wk.Ctx) -> dict[str, Any]:
        opts = [{"id": p["id"], "label": f"{p['label']}: {p['base_url']}"} for p in self._presets(ctx)]
        return ctx.say("Its base URL (OpenAI-compatible, ending in /v1 as a rule)?" + (" Pick a preset or type it."
                                                                                       if opts else ""),
                       options=opts, input={"kind": "text", "placeholder": "http://192.168.1.20:8080/v1"})

    def take_url(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        preset = next((p for p in self._presets(ctx) if p["id"] == reply.get("choice")), None)
        url = preset["base_url"] if preset else wf.unquote(reply.get("text"))
        if not re.match(r"^https?://[^\s/]+", url):
            ctx.say("A base URL starts with http:// or https://, for example http://127.0.0.1:8080/v1.")
            return None
        ctx.data.update(base_url=url, preset_model=(preset or {}).get("model") or "",
                        key_env=(preset or {}).get("key_env") or "")
        return "model"

    def ask_model(self, ctx: wk.Ctx) -> dict[str, Any]:
        given = ctx.data.get("preset_model")
        return ctx.say("Which model, by the name the server knows it by?",
                       options=[{"id": "preset", "label": given}] if given else [],
                       input={"kind": "text", "placeholder": "qwen3:32b"})

    def take_model(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        model = ctx.data.get("preset_model") if reply.get("choice") == "preset" else wf.unquote(reply.get("text"))
        if not model:
            return None
        ctx.data["model"] = model[:200]
        return "key" if ctx.data["kind"] == "hosted" else "confirm"

    def ask_key(self, ctx: wk.Ctx) -> dict[str, Any]:
        named = ctx.data.get("key_env")
        return ctx.say("Name the environment variable that holds its API key (for example OPENAI_API_KEY). Never "
                       "type the key itself here: to store a key, use the form in Models setup.",
                       options=[*([{"id": "named", "label": named}] if named else []),
                                {"id": "none", "label": "It needs no key"}],
                       input={"kind": "text", "placeholder": "MY_PROVIDER_API_KEY"})

    def take_key(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        from kernel.models_setup import KEY_NAME

        if reply.get("choice") in ("named", "none"):
            ctx.data["key_env"] = ctx.data.get("key_env") if reply["choice"] == "named" else ""
            return "confirm"
        text = wf.unquote(reply.get("text"))
        if KEY_NAME.match(text):
            ctx.data["key_env"] = text
            return "confirm"
        ctx.w["messages"][-1]["text"] = "(not kept: it was not a variable's name)"
        ctx.say("That is not a variable's name, so I did not keep it" + (": it looks like a key. If it is one, "
                "change it at the provider, since it was typed into a chat." if LOOKS_LIKE_KEY.search(text) else ".")
                + " A name is capital letters, digits and _, like OPENAI_API_KEY.")
        return None

    def ask_confirm(self, ctx: wk.Ctx) -> dict[str, Any]:
        d = ctx.data
        args = {"role": d["role"], "base_url": d["base_url"], "model": d["model"], "key_env": d.get("key_env") or None,
                "private": d["kind"] == "network"}
        return ctx.say("Ready. Nothing has changed yet. It is written to this machine's routing overlay, never to the "
                       "shipped routing; the ledger records who set which role to which host.", proposal={
                           "action": "set_model", "label": f"Set the {d['role'].replace('_', ' ')} to {d['model']}",
                           "lines": [f"Base URL: {d['base_url']}", f"Model: {d['model']}",
                                     "Key: " + (f"from {d['key_env']}" if d.get("key_env") else "none"),
                                     *(["On my own network: confidential projects may use it"]
                                       if d["kind"] == "network" else [])], "args": args})

    def done_confirm(self, ctx: wk.Ctx, prop: dict[str, Any], result: dict[str, Any]) -> str:
        role = result.get("role") or {}
        if role.get("note"):
            ctx.say(str(role["note"]))
        return "test"

    def ask_test(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Set. Test it now? Test sends it a tiny prompt and says how fast it answered, or the error.",
                       options=[{"id": "test", "label": "Run Test"}, {"id": "finish", "label": "Done"}], final=True)

    def take_test(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        from kernel.models_setup import probe_role

        got = wf.pick(ctx, reply, wk.offered(ctx.w))
        if got == "finish":
            return "done"
        if got != "test":
            return None
        out = probe_role(ctx.data["role"])
        ctx.say((f"It answered in {out['latency_ms']} ms" + (f": “{out['reply']}”." if out.get("reply") else ".")) if
                out["ok"] else f"The test failed: {out['error']}.", test=out,
                options=[{"id": "test", "label": "Test again"}, {"id": "finish", "label": "Done"}])
        return None

    def ask_done(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Done. Models setup (Settings, Models) shows every role and changes them.", final=True,
                       links=[{"label": "Open Models setup", "route": "#/models"}])


class Tour(wf.Flow):
    name, label, control = "tour", "Get started", "walk_tour"
    about = "a five-stop tour: Home, the Inbox, a project and What's next, Project settings, Ask Rihma"
    intro = "A short tour in five stops. Each stop takes you there and shows the place; Next goes on."
    first = "home"
    steps = ("home", "inbox", "project", "settings", "assistant", "done")

    def untick(self, ctx: wk.Ctx, exclude: list[str]) -> None:
        ctx.say("There is no folder in this tour.")

    @staticmethod
    def _project(ctx: wk.Ctx) -> str | None:
        from kernel.learn import FACTORY_PID

        made = [p for p in ctx.factory.projects() if p.pid != FACTORY_PID]
        return made[-1].pid if made else None

    def _stop(self, ctx: wk.Ctx, n: int, text: str, route: str, control: str | None) -> dict[str, Any]:
        last = n == 5
        return ctx.say(f"{n} of 5. {text}", navigate={"route": route, "control": control},
                       options=[{"id": "next", "label": "Finish" if last else "Next"}])

    def ask_home(self, ctx: wk.Ctx) -> dict[str, Any]:
        return self._stop(ctx, 1, "Home is your dashboard for your lens: key figures, decisions waiting, and more. "
                                  "Customize changes what it shows.", "#/home", "customize")

    def ask_inbox(self, ctx: wk.Ctx) -> dict[str, Any]:
        return self._stop(ctx, 2, "The Inbox holds every decision that waits on a person, across projects; a card "
                                  "shows who may decide it.", "#/inbox", None)

    def ask_project(self, ctx: wk.Ctx) -> dict[str, Any]:
        pid = self._project(ctx)
        if pid is None:
            return self._stop(ctx, 3, "You have no project yet: they are listed here, and New project starts one. "
                                      "Each project's overview says What's next.", "#/projects", "new_project")
        return self._stop(ctx, 3, "A project's overview says What's next: what it waits for, who can act, and the "
                                  "buttons that move it on.", f"#/p/{pid}/overview", "next_step")

    def ask_settings(self, ctx: wk.Ctx) -> dict[str, Any]:
        pid = self._project(ctx)
        if pid is None:
            return self._stop(ctx, 4, "Project settings, on a project's overview, change its kind of work, mode, "
                                      "maturity, title and posture later, with a preview first.", "#/projects", None)
        return self._stop(ctx, 4, "Project settings change the kind of work, mode, maturity, title and posture, with a "
                                  "preview of what it means first.", f"#/p/{pid}/overview", "project_settings")

    def ask_assistant(self, ctx: wk.Ctx) -> dict[str, Any]:
        return self._stop(ctx, 5, "Ask Rihma, here, answers where things are and what they mean, proposes actions you "
                                  "confirm, and runs these walkthroughs. Press / to open it anywhere.", "#/home",
                          "assistant")

    def _next(self, ctx: wk.Ctx, reply: dict[str, Any], to: str) -> str | None:
        return to if wf.pick(ctx, reply, wk.offered(ctx.w)) == "next" or wf.yes_no(reply.get("text")) else None

    def take_home(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        return self._next(ctx, reply, "inbox")

    def take_inbox(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        return self._next(ctx, reply, "project")

    def take_project(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        return self._next(ctx, reply, "settings")

    def take_settings(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        return self._next(ctx, reply, "assistant")

    def take_assistant(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        return self._next(ctx, reply, "done")

    def ask_done(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("That is the tour. Walkthroughs, on Home and here, also plug in a project, start from an idea "
                       "or documents, and set up a model.", final=True)


FLOWS = {"new_idea": NewIdea(), "model": Model(), "tour": Tour()}
