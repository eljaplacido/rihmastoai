"""A project's data flow as a diagram (FR-ITD1): sources, Rihmasto, its agents, and where data goes.

``build(items, agents, title)`` turns the project's connections (kernel/itdata.py) and its agents' reach
(kernel/itdata_project.py ``agents``) into four columns of nodes and the edges between them; the cockpit draws them
as an SVG whose nodes open the connection they stand for (cockpit/static/itdata_flow.js):

- **where data comes from**: you and your team (requests, answers, material), inbound webhooks, website chats,
  connectors and the data integrations the product declares;
- **Rihmasto**, on this machine;
- **agents**: Rihma's roles, coding agents through the AI tool connection, and the delivered product;
- **where data goes**: the model endpoints each role sends its prompts to, where the product runs, the relay's
  channels and the registries, plus the integrations the product writes to.

An edge whose end is outside this machine and your network (or whose address is not known here) is marked
``leaves``: the diagram draws it apart, and "which data leaves the machine?" lists the same. Nothing is written.
"""

from __future__ import annotations

from typing import Any

from kernel import itdata as it

COLUMNS = [{"id": "sources", "label": "Where data comes from"}, {"id": "rihmasto", "label": "Rihmasto"},
           {"id": "agents", "label": "Agents"}, {"id": "destinations", "label": "Where data goes"}]
SOURCE_KINDS = ("hook", "chat", "connector", "integration")
DEST_KINDS = ("model", "road", "relay", "registry")
INTO_RIHMASTO = ("hook", "chat", "connector")


def _node(nid: str, column: str, label: str, *, where: str = it.LOCAL, state: str | None = None,
          item: str | None = None, agent: str | None = None, sub: str | None = None) -> dict[str, Any]:
    return {"id": nid, "column": column, "label": label, "locality": where, "state": state, "item": item,
            "agent": agent, "sub": sub or where}


def _item_node(x: dict[str, Any], column: str) -> dict[str, Any]:
    sub = ("refused: confidential" if x.get("refused") else x["locality"])
    return _node("n:" + x["id"], column, x["label"], where=x["locality"], state=x.get("state"), item=x["id"], sub=sub)


def _edge(a: str, b: str, *, leaves: bool = False, label: str | None = None) -> dict[str, Any]:
    return {"from": a, "to": b, "leaves": leaves, "label": label}


def _sources(items: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    nodes = [_node("n:people", "sources", "You and your team", sub="requests, answers, material")]
    edges = [_edge("n:people", "n:rihmasto")]
    for x in items:
        if x["kind"] not in SOURCE_KINDS:
            continue
        nodes.append(_item_node(x, "sources"))
        target = "n:rihmasto" if x["kind"] in INTO_RIHMASTO else "n:agent:product"
        edges.append(_edge("n:" + x["id"], target, label=", ".join(x["data_classes"][:2]) or None))
        if x["direction"] == "both":     # what goes back: the product's writes, a website chat's answers to visitors
            back = ("n:agent:product", "writes") if x["kind"] == "integration" else ("n:rihmasto", "answers")
            edges.append(_edge(back[0], "n:" + x["id"], leaves=it.leaves(x), label=back[1]))
    return nodes, edges


def _agents(agents: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    nodes, edges = [], []
    for a in agents:
        sub = "blocked: needs a local model" if a.get("blocked") else "sends prompts outside" if a["leaves"] else \
            ("its models stay here" if a["models"] else None)
        nodes.append(_node("n:agent:" + a["id"], "agents", a["label"], agent=a["id"], sub=sub or "no model of its own"))
        edges.append(_edge("n:rihmasto", "n:agent:" + a["id"]))
    return nodes, edges


def _destinations(items: list[dict[str, Any]], agents: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    nodes, edges = [], []
    by_id = {x["id"]: x for x in items}
    for x in items:
        if x["kind"] in DEST_KINDS:
            nodes.append(_item_node(x, "destinations"))
    for a in agents:
        for mid in a["models"]:
            edges.append(_edge("n:agent:" + a["id"], "n:" + mid, leaves=it.leaves(by_id[mid]), label="prompts"))
    for x in items:
        if x["kind"] == "road":
            edges.append(_edge("n:agent:product", "n:" + x["id"], leaves=it.leaves(x), label="runs"))
        elif x["kind"] in ("relay", "registry"):
            edges.append(_edge("n:rihmasto", "n:" + x["id"], leaves=it.leaves(x),
                               label="events" if x["kind"] == "relay" else "images"))
    return nodes, edges


def build(items: list[dict[str, Any]], agents: list[dict[str, Any]], title: str) -> dict[str, Any]:
    """The diagram's columns, nodes and edges; an edge to a missing node is left out."""
    src_n, src_e = _sources(items)
    ag_n, ag_e = _agents(agents)
    dst_n, dst_e = _destinations(items, agents)
    nodes = src_n + [_node("n:rihmasto", "rihmasto", "Rihmasto", sub="this machine")] + ag_n + dst_n
    ids = {n["id"] for n in nodes}
    edges = [e for e in src_e + ag_e + dst_e if e["from"] in ids and e["to"] in ids]
    return {"title": title, "columns": COLUMNS, "nodes": nodes, "edges": edges,
            "leaving": sorted({e["to"] for e in edges if e["leaves"]})}
