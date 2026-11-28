"""What applies where (D-0027, FR-TM3): for every setting or configuration surface, the scopes it can be set at, and
for a project where its value comes from right now.

The owner (2026-11-27): "Every setting and term shows its scope: this project, this team, or the shipped default." The
one table is ``SURFACES``. Each surface says the scopes it may be set at (``default`` is what Rihmasto ships,
``home`` one setting every team shares, ``team`` a team's own words, ``project`` one project's own, ``personal`` a
person's own look), the controls of
the cockpit's map (cockpit/ui_map.json) it covers, where to change it at each scope, and how to read its present value
source. ``rows`` renders it for a project, or for the team; a test iterates the map's controls on Settings and fails for
one that no surface covers. Ask Rihma answers "where is this set?" from the same rows (kernel/teams_chat.py).

A surface is set for the whole home (``home``: every team in it shares one value, so it is never called a team's), or
per project, or per team (only the words, and who is in a team). Each reads its value source from the store it is kept
in (kernel/scope_sources.py). Nothing here changes a setting: a link says where.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel import scope_sources

SCOPE_WORD = {"default": "Shipped default", "home": "All teams", "team": "This team", "project": "This project",
              "personal": "You"}
SOLO_SCOPE_WORD = {**SCOPE_WORD, "home": "All projects", "team": "Your words"}      # one person: no team to speak of
SOURCE_WORD = {"project": "this project's own", "home": "set for all teams", "team": "from the team",
               "default": "shipped default", "none": "nothing set here yet", "per_project": "made on each project",
               "personal": "your own, in this browser"}
SOLO_SOURCE_WORD = {**SOURCE_WORD, "home": "set for all your projects", "team": "from your words"}
TOP_ROUTES = {"settings": "#/settings", "connections": "#/connections", "share": "#/share",
              "automations_all": "#/automations", "health_all": "#/health"}      # the pages outside a project
Reader = Callable[[Any, Any], str]
_fixed = lambda scope: (lambda factory, project: scope)       # noqa: E731  (a surface that is only ever one scope)


# (id, label, scopes it may be set at, the map's controls it covers, change it for the team, change it for a project,
#  how its present value source is read: kernel/scope_sources.py)
Link = tuple[str, str] | None          # (page or project view, control)
S = scope_sources
SURFACES: list[tuple[str, str, tuple[str, ...], tuple[str, ...], Link, Link, Reader]] = [
    ("structure", "Rihmasto's structure: how much of its own way to ask for", ("default", "home", "project"),
     ("structure_policy", "structure_preview"), ("settings", "structure_policy"), ("align", "structure_policy"),
     S.structure),
    ("enforcement", "Enforcement levels per environment and who reviews", ("default", "home", "project"),
     ("enforcement_platform", "enforcement_preview", "enforcement_levels"), ("settings", "enforcement_platform"),
     ("enforcement", "enforcement_levels"), S.enforcement),
    ("harness", "Gnomon's enforcement and what each harness enforces", ("default", "home", "project"),
     ("harness_effects", "enforcement_set"), ("settings", "harness_effects"), ("who", "enforcement_set"), S.harness),
    ("itops", "IT checks and check sets", ("default", "home", "project"), ("itops_defaults", "itops_set"),
     ("connections", "itops_defaults"), ("itops", "itops_set"), S.itops),
    ("modules", "Modules in use", ("default", "home", "project"), ("modules",), ("settings", "modules"),
     ("settings", "modules"), S.modules),
    ("runners", "Cell runners", ("default", "home", "project"), ("runners_open", "runners_set", "project_runner"),
     ("settings", "runners_open"), ("overview", "project_runner"), S.runners),
    ("roads", "Paved roads and connectors", ("default", "home", "project"),
     ("paved_roads", "configure_gcp_road", "drive_connector"), ("settings", "paved_roads"), ("releases", "choose_road"),
     S.roads),
    ("models", "AI models per role", ("default", "home"), ("models_open",), ("settings", "models_open"), None,
     S.models),
    ("people", "People, personas and sign-in", ("default", "home"),
     ("people_access", "people_mode", "people_name", "people_add_user", "people_invite", "people_deactivate",
      "people_map_group", "people_role", "people_views", "people_idp", "people_keys", "people_test_token",
      "people_delegate_agent", "people_agents"), ("settings", "people_access"), None, S.people),
    ("folders", "Folders the cockpit may read", ("default", "home"), ("allow_folder",), ("settings", "allow_folder"),
     None, S.folders),
    ("observability", "Agent observability hub", ("default", "home"), ("agent_observability_settings",),
     ("settings", "agent_observability_settings"), None, S.observability),
    ("embeds", "Embeds: a chat window for a website", ("project", "home"), ("create_embed", "revoke_embed"),
     ("settings", "create_embed"), ("settings", "create_embed"), S.embeds),
    ("observer", "Observer links", ("project", "home"), ("observe_link", "observe_revoke"), ("share", "observe_link"),
     ("share", "observe_link"), S.observer),
    ("automations", "Automations", ("project", "home"), ("automations_open", "automations_new"),
     ("automations_all", "automations_new"), ("automations", "automations_new"), S.automations),
    ("evals", "Evals and what they check", ("project",), ("evals_run", "evals_all"), ("health_all", "evals_all"),
     ("checks", "evals_run"), S.evals),
    ("vocabulary", "Vocabulary: Rihmasto's own words", ("default", "team", "project"),
     ("vocab_team", "vocab_project", "vocab_preview", "vocab_undo"), ("settings", "vocab_team"),
     ("vocabulary", "vocab_project"), S.vocabulary),
    ("teams", "Teams and the team a project is in", ("default", "team", "project"),
     ("teams_page", "teams_set", "teams_preview", "teams_undo", "teams_move"), ("settings", "teams_page"),
     ("overview", "teams_move"), S.teams_row),
    ("machines", "Machines your agents are on", ("default", "home"),
     ("machines_page", "machine_add", "machine_remove", "reach_test"), ("settings", "machines_page"), None, S.machines),
    ("asks", "Asks to agents on other machines", ("project",), ("ask_put",), None, ("agents", "ask_put"), S.asks),
    ("appearance", "Appearance: mode, accent, density", ("default", "personal"), ("theme", "density"), None, None,
     _fixed("personal")),
    ("about", "About and help", ("default",), ("about_help",), ("settings", "about_help"), None, _fixed("default")),
    ("scope", "What applies where", ("default",), ("scope_view",), ("settings", "scope_view"), None, _fixed("default")),
]
COVERED = {c for s in SURFACES for c in s[3]}


def covers(control: str) -> str | None:
    """The surface that covers a control of the map, or None."""
    return next((s[0] for s in SURFACES if control in s[3]), None)


def _link(link: Link, project: Any) -> dict[str, str] | None:
    if link is None:
        return None
    page, control = link
    if page in TOP_ROUTES:
        return {"route": TOP_ROUTES[page], "control": control}
    return {"route": f"#/p/{project.pid}/{page}", "control": control} if project is not None else None


def _word(sid: str, scopes: tuple[str, ...], source: str, factory: Any, project: Any, solo: bool) -> str:
    """The value source in words: the surface's own where it says more (the team a project is in), else the table's."""
    if sid == "teams" and project is not None and source == "project":
        from kernel import teams

        return f"this project is in {teams.read(factory, teams.team_of(factory, project))['name']}"
    if source == "project" and "default" not in scopes:
        return "made on this project"
    return (SOLO_SOURCE_WORD if solo else SOURCE_WORD)[source]


def rows(factory: Any, project: Any = None) -> list[dict[str, Any]]:
    """Each surface with its scopes, where its value comes from for ``project`` (the home's reading without one), and
    where to change it. A home of one person says "all projects" where several teams say "all teams"."""
    from kernel import teams

    solo, out = teams.is_solo(factory), []
    words = SOLO_SCOPE_WORD if solo else SCOPE_WORD
    for sid, label, scopes, controls, team_link, proj_link, reader in SURFACES:
        try:
            source = reader(factory, project)
        except (OSError, ValueError, KeyError):
            source = "default"
        out.append({"id": sid, "label": label, "scopes": list(scopes), "scope_words": [words[s] for s in scopes],
                    "controls": list(controls), "source": source,
                    "source_word": _word(sid, scopes, source, factory, project, solo),
                    "change_for_team": _link(team_link, None), "change_for_project": _link(proj_link, project)
                    if project is not None else None, "set_per_project": "project" in scopes})
    return out


def describe(factory: Any, project: Any = None) -> dict[str, Any]:
    from kernel import teams

    team = teams.read(factory, teams.team_of(factory, project)) if project is not None else None
    solo = teams.is_solo(factory)
    return {"project": project.pid if project is not None else None, "solo": solo,
            "team": {"id": team["id"], "name": team["name"]} if team else None, "rows": rows(factory, project),
            "scope_words": SOLO_SCOPE_WORD if solo else SCOPE_WORD,
            "source_words": SOLO_SOURCE_WORD if solo else SOURCE_WORD}
