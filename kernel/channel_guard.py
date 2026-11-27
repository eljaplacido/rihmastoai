"""The agent channel holds up in daily use (FR-CHN3): what keeps it answering, once, within its limits.

FR-CHN2 made the channel useful; an independent check then found how daily use broke it. Here:

- ``fit`` and ``shorten``: Rihma's own posts always fit the channel's limit. A person may write up to
  ``agent_channel.MAX_TEXT`` characters (a pasted log, a stack trace); Rihma's question to an agent quotes it
  shortened at a sentence or a word, and names the person's message that holds it whole;
- ``refused``: when the channel still refuses one of Rihma's posts, the message gets a short system note saying so
  (and why), so it counts as answered: the channel view never fails on it again and no background answer dies on
  it quietly;
- ``once``: each message is answered once. The panel polls (``GET .../channel`` answers what waits) while a post
  is being answered; whoever comes second finds the message claimed, or answered, and leaves it;
- ``counts_toward_cap``: the limit of Rihma's replies an hour is there so two agents cannot set each other off.
  Only Rihma's answers to an agent's message count; a person's own questions, and Rihma's question to an agent made
  for a person, never use it up;
- ``said``: what happened to a person's post, in one line, for the route's answer (Ask Rihma's Confirm shows it):
  the question put to the agent, answered, or not put to it and why.
"""

from __future__ import annotations

import contextlib
import re
import threading
from collections.abc import Iterator
from typing import Any

from kernel import agent_channel as ch

_LOCK = threading.Lock()
_BUSY: set[tuple[str, str]] = set()      # (the channel's file, a message id) being answered now, in this process
_END = re.compile(r"[.!?\n](?=\s)")


# -- fitting -------------------------------------------------------------------------------------------------

def shorten(text: str, room: int) -> str:
    """``text`` whole when it fits ``room``, else cut at the last sentence (or word) that fits, with an ellipsis."""
    text = str(text or "").strip()
    if len(text) <= room:
        return text
    room = max(room - 1, 1)
    head = text[:room]
    ends = [m.end() for m in _END.finditer(head)]
    cut = ends[-1] if ends and ends[-1] > room // 2 else (head.rfind(" ") if head.rfind(" ") > room // 2 else room)
    return head[:cut].rstrip(" ,;:-\n") + "…"


def fit(text: str, limit: int = ch.MAX_TEXT) -> str:
    """Text that the channel takes: whole when it fits, else shortened to exactly ``limit`` characters or fewer."""
    out = shorten(text, limit)
    return out if len(out) <= limit else out[: limit - 1] + "…"


# -- answering once ----------------------------------------------------------------------------------------

def answer_of(project: Any, mid: str) -> dict[str, Any] | None:
    """Rihma's (or the system's) last post that answers ``mid``, or None."""
    found = [m for m in ch.read(project).get("messages") or [] if m["author"]["kind"] in ("rihma", "system")
             and (m.get("refs") or {}).get("message") == mid]
    return found[-1] if found else None


def busy(project: Any, mid: str) -> bool:
    with _LOCK:
        return (str(project.path(ch.FILE)), mid) in _BUSY


@contextlib.contextmanager
def once(project: Any, mid: str) -> Iterator[bool]:
    """True for the one caller that may answer ``mid`` now; False while another answers it, or once answered."""
    key = (str(project.path(ch.FILE)), mid)
    with _LOCK:
        mine = key not in _BUSY and answer_of(project, mid) is None
        if mine:
            _BUSY.add(key)
    try:
        yield mine
    finally:
        if mine:
            with _LOCK:
                _BUSY.discard(key)


def refused(project: Any, msg: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """A short note when the channel refused Rihma's answer: the message counts as answered, and the person reads
    why and what to do."""
    why = shorten(str(exc.args[0] if exc.args else exc), 300)
    return ch.post(project, author=ch.SYSTEM, kind="note", thread=msg["thread"], refs={"message": msg["id"]},
                   text=f"Rihma could not answer {msg['id']}: {why}. Ask again in fewer words, or split it.")


# -- the hourly cap ---------------------------------------------------------------------------------------

def counts_toward_cap(m: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    """Whether a message in the last hour is one of Rihma's replies the cap counts: an answer to an agent's (or an
    automation's) message. Rihma's questions to agents and its answers to people are not."""
    if m["author"]["kind"] != "rihma" or m["kind"] != "answer":
        return False
    to = by_id.get(str((m.get("refs") or {}).get("message") or ""))
    return to is None or to["author"]["kind"] not in ("person",)


def capped(msg: dict[str, Any]) -> bool:
    """Whether the cap applies to ``msg`` at all: a person's message is always answered."""
    return msg["author"]["kind"] != "person"


# -- what happened, in one line ---------------------------------------------------------------------------

def said(project: Any, msg: dict[str, Any], answer: dict[str, Any] | None) -> str:
    """What happened to a person's post: for the route's answer, and Ask Rihma's Confirm."""
    if answer is None:
        return ("Posted. Rihma is answering it now." if busy(project, msg["id"]) else
                f"Posted as {msg['id']}.")
    if answer["author"]["kind"] == "system":
        return f"Posted as {msg['id']}. Not put to the agent: {shorten(answer['text'], 400)}"
    asked = [m for m in ch.read(project).get("messages") or [] if m["author"]["kind"] == "rihma"
             and m["kind"] == "question" and (m.get("refs") or {}).get("message") == msg["id"]]
    if asked:
        to = ", ".join(asked[-1].get("to") or []) or "the agent"
        return (f"Rihma put your question to {to} in the agent channel ({asked[-1]['id']}); its answer comes back "
                "there.")
    return f"Posted as {msg['id']}; Rihma answered it ({answer['id']})."
