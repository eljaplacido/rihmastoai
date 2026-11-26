"""Where each control of the cockpit's map is (cockpit/ui_map.json): the project view it is on, and the page it
is on outside a project. kernel/assistant_rules.py ``ui_map`` adds both to each control, and Take me there opens
that page, then highlights the control. Each part of the cockpit adds its controls in its own block below.
"""

from __future__ import annotations

# Where each control of the map is: the project view it is on, and the page it is on outside a project.
# (None, None) is the shell, on every page. Take me there opens that page, then highlights the control.
CONTROL_PAGES: dict[str, tuple[str | None, str | None]] = {
    "persona": (None, None), "lens": (None, None), "palette": (None, None), "assistant": (None, None),
    "theme": (None, None), "density": (None, None), "new_project": (None, "projects"),
    "adopt_project": (None, "projects"), "scan_source": (None, "projects"), "confidential": (None, "projects"),
    "customize": (None, "home"),
    "pause": ("overview", None), "resume": ("overview", None), "autonomy": ("overview", None),
    "answer": ("questions", "inbox_all"), "assume": ("questions", None), "decide": ("inbox", "inbox_all"),
    "report": ("changes", None), "comment": ("spec", None), "log_signal": (None, "square"),
    "validate_concept": (None, "square"), "export_evidence": ("evidence", None), "build_pack": ("releases", None),
    "create_embed": (None, "settings"), "intake_summary": ("questions", None),
    "track_pill": ("overview", None), "track_settings": ("track", None),
    "checkpoint_look": ("track", None), "autopilot_start": ("track", None), "autopilot_stop": ("track", None),
    "revoke_delegation": ("track", None),
    "choose_outputs": ("outputs", None), "build_output": ("outputs", None),
    "build_outputs": ("outputs", None), "download_output": ("outputs", None), "modules": (None, "settings"),
    "revoke_embed": (None, "settings"),
    "project_settings": ("overview", None), "rewind_project": ("overview", None), "add_material": ("overview", None),
    "next_step": ("overview", None), "go_ahead": ("overview", None), "build_without_waiting": ("overview", "projects"),
    "shape_open": (None, "home"), "shape_start": (None, "shape"),
    "shape_say": (None, "shape"), "shape_attach": (None, "shape"), "shape_draft": (None, "shape"),
    "shape_create": (None, "shape"), "models_open": (None, "settings"), "models_set": (None, "models"),
    "models_test": (None, "models"), "models_remove": (None, "models"), "models_preset": (None, "models"),
    "models_private": (None, "models"), "models_use_claude": (None, "models"), "models_use_codex": (None, "models"),
    "models_use_opencode": (None, "models"), "posture": ("overview", None), "run_assessment": ("assessment", None),
    "assessment_changes": ("assessment", None), "capability_faces": ("releases", None), "access": (None, None),
    "ai_tools": ("overview", None), "ide_setup": ("overview", None), "ide_section": ("overview", None),
    "integrations": ("plan", None), "runners_open": (None, "settings"), "runners_check": (None, "runners"),
    "runners_set": (None, "runners"), "runners_decide": (None, "runners"), "project_runner": ("overview", None),
    "automations_open": (None, "home"),
    "automations_new": ("automations", "automations_all"), "automations_template": ("automations", "automations_all"),
    "automations_save": ("automations", "automations_all"), "automations_run": ("automations", "automations_all"),
    "automations_dry_run": ("automations", "automations_all"), "automations_pause": ("automations", "automations_all"),
    "automations_resume": ("automations", "automations_all"), "automations_edit": ("automations", "automations_all"),
    "automations_remove": ("automations", "automations_all"), "automations_tags": ("automations", None),
    # real projects of every shape (FR-RPJ1): the scan step's choices, Settings' folders, an adopted project's page
    "scan_cancel": (None, "projects"), "allow_root": (None, "projects"), "adopt_again": (None, "projects"),
    "adopt_take": (None, "projects"), "adopt_workspace": (None, "projects"), "use_local_model": (None, "projects"),
    "scan_track": (None, "projects"), "adopt_usage": (None, "projects"), "allow_folder": (None, "settings"),
    "kind_not_chosen": ("overview", None), "adopted_state": ("overview", None), "watch_setup": ("overview", None),
    "baseline_stated": ("overview", None), "project_areas": ("overview", None)}
# Walkthroughs (FR-WLK1): the button on Home's header, and each walkthrough in the Ask Rihma panel (the shell).
CONTROL_PAGES.update({"walkthroughs": (None, "home"), "walk_plug_in": (None, None), "walk_new_idea": (None, None),
                      "walk_documents": (None, None), "walk_model": (None, None), "walk_tour": (None, None)})
# The console and Health (cockpit/static/console.js, cockpit/static/health.js; FR-CON1, FR-CHK1).
CONTROL_PAGES.update({
    "console_run": ("console", None), "console_gnomon": ("console", None), "console_stop": ("console", None),
    "console_terminal": ("console", None), "console_settings": ("console", None),
    "health_run": ("checks", None), "health_enable": ("checks", None), "health_disable": ("checks", None),
    "health_enable_all": (None, "health_all")})
# Alignment with a repository's own specs and tests (cockpit/static/alignment.js, FR-ALN1).
CONTROL_PAGES.update({"align_scan": ("align", None), "align_decide": ("align", None), "align_bulk": ("align", None),
                      "align_suggestions": ("align", None)})
# Insights (cockpit/static/insights.js, FR-INS1): the page across projects and a project's tab.
CONTROL_PAGES.update({"insights_dimension": ("insights", "insights_all"),
                      "insights_window": ("insights", "insights_all"), "insights_scope": (None, "insights_all"),
                      "insights_export": ("insights", "insights_all"), "insights_pin": (None, "insights_all")})
# The Knowledge graph (cockpit/static/graph.js, FR-GRV1): a project's tab and the page across projects.
CONTROL_PAGES.update({"graph_filters": ("graph", "graph_all"), "graph_mode": ("graph", "graph_all"),
                      "graph_focus": ("graph", "graph_all"), "graph_presets": ("graph", "graph_all"),
                      "graph_pin": ("graph", "graph_all")})
# Since you last looked (FR-REV1, cockpit/static/review.js).
CONTROL_PAGES.update({"review_card": (None, "home"), "mark_all_reviewed": ("review", "review_all"),
                      "review_mark": ("review", "review_all"), "review_digest": (None, "review_all")})
# The paved roads and the Google Drive connector (kernel/road_settings.py, cockpit/static/roads.js).
CONTROL_PAGES.update({"paved_roads": (None, "settings"), "configure_gcp_road": (None, "settings"),
                      "choose_road": ("releases", None), "drive_connector": (None, "settings")})
# Goal help, the hand-off and the agent channel (cockpit/static/goal.js, agents.js; FR-CPL1, FR-BRG1, FR-CHN1).
CONTROL_PAGES.update({
    "handoff": ("overview", None), "channel_panel": ("overview", None), "agents_strip": ("overview", None),
    "channel_post": ("agents", None), "channel_pause": ("agents", None), "channel_settle": ("agents", None),
    "channel_trace": ("agents", None), "goal_plan": (None, None), "agent_activity": (None, "agents_all")})
# The data and context layer (cockpit/static/context.js; FR-CTX1): the project's Context view and the Data page.
CONTROL_PAGES.update({"context_pack": ("context", None), "context_audit": ("context", None),
                      "context_health": (None, "data_all"), "data_cleanup": (None, "data_all"),
                      "data_apply": (None, "data_all")})
# Where the capability goes (cockpit/static/destinations.js, FR-DST1): the Destinations tab and the overview's card.
CONTROL_PAGES.update({
    "destinations_map": ("destinations", None), "destinations_where": ("overview", None),
    "destinations_deliver": ("destinations", None), "destinations_promote": ("destinations", None),
    "destinations_publish": ("destinations", None), "destinations_check": ("destinations", None),
    "destinations_investigate": ("destinations", None)})
# Integrations and data, IT's view (cockpit/static/itdata.js, FR-ITD1): a project's view and the platform's page.
CONTROL_PAGES.update({
    "itdata_map": ("itdata", "connections"), "itdata_flow": ("itdata", None), "itdata_stores": (None, "connections"),
    "itdata_check": ("itdata", "connections"), "itdata_disable": ("itdata", "connections"),
    "itdata_rotate": ("itdata", "connections")})
# What IT checks (cockpit/static/itops.js, FR-ITO1): a project's view; the defaults on Integrations and data.
CONTROL_PAGES.update({
    "itops_set": ("itops", None), "itops_apply": ("itops", None), "itops_run": ("itops", None),
    "itops_override": ("itops", None), "itops_types": ("itops", None), "itops_assess": ("itops", None),
    "itops_defaults": (None, "connections"), "itops_default_change": (None, "connections"),
    "itops_evalsets": ("itops", "agentops_all"), "itops_evalset": ("itops", None)})
# Set up this project, the automations' suggestions and Describe it, archive and remove (FR-SET1, setup.js).
CONTROL_PAGES.update({
    "setup_checklist": ("overview", None), "setup_do": ("overview", None),
    "automations_suggest": ("automations", "automations_all"),
    "automations_suggest_accept": ("automations", "automations_all"),
    "automations_suggest_dismiss": ("automations", "automations_all"),
    "automations_describe": ("automations", "automations_all"), "archive_project": ("overview", None),
    "archived_projects": (None, "projects"), "restore_project": (None, "projects"),
    "remove_project": (None, "projects")})

# Controls from the stable line merged in (assessment priorities, jobs, the Inbox's batches, understanding, live
# progress, the folder picker, guided journeys, capsules and scope): where each one is.
CONTROL_PAGES.update({
    'assessment_ask': ('assessment', None),
    'job_ask': (None, 'jobs'),
    'inbox_batch_decide': ('inbox', None),
    'inbox_batch_assume': ('inbox', None),
    'understood_correct': ('overview', None),
    'assessment_progress': ('assessment', None),
    'cancel_assessment': ('assessment', None),
    'assessment_progress_card': ('overview', None),
    'scan_progress': (None, 'projects'),
    'pick_browse': (None, 'projects'),
    'pick_here': (None, 'projects'),
    'journey_guide': (None, None),
    'journey_do': (None, None),
    'journey_did': (None, None),
    'journey_skip': (None, None),
    'journey_stop': (None, None),
    'journey_next': ('overview', None),
    'journey_starters': (None, 'projects'),
    'scope_switch': (None, None),
    'capsules': ('overview', None),
    'customize_view': (None, None),
    'customize_tabs': ('overview', None),
    'square_scope': (None, 'square'),
    'assistant_scope': (None, None),
})

# Agent observability, people and access, Gnomon's audits and evals, self-healing (FR-OBS1, FR-PPL1, FR-EVL1,
# FR-HEAL1): where each control is.
CONTROL_PAGES.update({
    'agent_sessions_map': ('agent_sessions', None),
    'agent_sessions_snapshot': ('agent_sessions', None),
    'agent_observability_settings': (None, 'settings'),
    'agent_sessions_enable': ('overview', None),
    'agent_observability_hooks': ('overview', None),
    'people_access': (None, 'settings'),
    'people_mode': (None, 'settings'),
    'people_name': (None, 'settings'),
    'people_add_user': (None, 'settings'),
    'people_invite': (None, 'settings'),
    'people_deactivate': (None, 'settings'),
    'people_map_group': (None, 'settings'),
    'people_role': (None, 'settings'),
    'people_views': (None, 'settings'),
    'people_idp': (None, 'settings'),
    'people_keys': (None, 'settings'),
    'people_test_token': (None, 'settings'),
    'people_delegate_agent': (None, 'settings'),
    'people_agents': (None, 'settings'),
    'viewing_as': (None, 'inbox_all'),
    'evals_run': ('checks', None),
    'evals_make_change': ('checks', None),
    'evals_history': ('checks', None),
    'evals_all': (None, 'health_all'),
    'evals_roles_run': (None, 'models'),
    'incidents_open': ('incidents', 'incidents_all'),
    'report_problem': (None, None),
    'give_feedback': (None, None),
    'investigate_incident': ('incidents', 'incidents_all'),
    'take_remedy': ('incidents', 'incidents_all'),
    'resolve_incident': ('incidents', 'incidents_all'),
    'approve_remedy': (None, 'incidents_all'),
    'retire_remedy': (None, 'incidents_all'),
    'prepare_fix': ('incidents', 'incidents_all'),
    'open_pr': ('incidents', 'incidents_all'),
    'approve_feedback': (None, 'incidents_all'),
    'about_help': (None, 'settings'),   # About and help (FR-PUB2)
})
# Never lost, who acted and decision triage (cockpit/static/neverlost.js, triage.js, whoacted.js; FR-NVL1).
CONTROL_PAGES.update({
    "why_ask": (None, None), "triage_assume": ("triage", None), "triage_open": ("triage", None),
    "assumption_grew": ("triage", None), "who_acted": ("who", None), "harness_effects": ("who", "settings"),
    "enforcement_set": ("who", "settings"),
})
CONTROL_PAGES.update({"triage_assume": ("triage", "decide"), "triage_open": ("triage", "decide")})   # FR-NVL2
# Agent operations, the AI architect's view (FR-AOP1): across projects and in a project's Agents capsule.
CONTROL_PAGES.update({control: ("agentops", "agentops_all") for control in (
    "agent_ops_window", "agent_ops_drill", "agent_ops_audit", "agent_ops_change", "agent_ops_price")})
# The development board, its briefing, and the trace with the session hooks (devboard.js, devtrace.js; FR-DEV1).
CONTROL_PAGES.update({"dev_briefing": ("board", None), "dev_seen": ("board", None),
                      "dev_filters": ("trace", None), "dev_hooks": ("trace", None)})

# Enforcement levels per environment (cockpit/static/enforcement.js, FR-ENF1): a project's view and Settings.
CONTROL_PAGES.update({
    "enforcement_levels": ("enforcement", None), "enforcement_platform": (None, "settings"),
    "enforcement_preview": ("enforcement", "settings"), "enforcement_pipeline": ("enforcement", None),
    "enforcement_take_pipeline": ("enforcement", None), "enforcement_repo": ("enforcement", None),
    "enforcement_ask": ("enforcement", None)})
# FR-ENF2: a review decided in place, stage names and the gate's stage; the Inbox's "View as everything".
CONTROL_PAGES.update({
    "enforcement_decide": ("enforcement", None), "enforcement_places": ("enforcement", None),
    "inbox_view_all": ("inbox", "inbox_all")})
# People in the loop (cockpit/static/hitl.js, FR-HITL1): the project's view in the Govern capsule.
CONTROL_PAGES.update({c: ("loop", None) for c in (
    "hitl_waiting", "hitl_ask", "hitl_answer", "hitl_send", "hitl_link", "hitl_link_copy", "hitl_link_revoke",
    "hitl_nudge", "hitl_enforce", "hitl_channels")})
