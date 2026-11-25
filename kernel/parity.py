"""UI and chat parity (FR-SET1): every way to change something is there by a click, in Ask Rihma and on the cockpit.

The owner (2026-11-24): "make sure that when you know how it happens I can also do it on a UIX level or by agent
request on chat." These tables say, for every control of the cockpit's map (cockpit/ui_map.json), how Ask Rihma
does the same; for every assistant action, the control that does it by hand; and for every signed command of the
command line, the cockpit route that does it, or why not. tests/test_parity.py reads them against the code, so a
control, an action or a command added without its other half fails until it gets one, or a recorded reason.

A control's chat path is one of:

- ``("action", name)``: an assistant action of kernel/assistant_rules.py ``ACTIONS``;
- ``("op", name)``: an ``act`` operation of kernel/assistant_ops.py ``OPS``;
- ``("walk", id)``: a walkthrough in Ask Rihma (kernel/walkthrough.py);
- ``("goal", intent)``: a goal plan's step (kernel/copilot.py ``INTENTS``);
- ``("chat", "module:function")``: Ask Rihma answers it with that function (kernel/setup_chat.py ...);
- ``("open", reason)``: Ask Rihma takes the person to it (Take me there), and the reason says why the act itself
  stays a click there: a file to download, a judgement made beside what it judges, a secret on IT's machine.

``READS`` are the controls that change nothing (a view, a filter, a copy, a preview).
"""

from __future__ import annotations

READS = frozenset({
    "persona", "lens", "palette", "assistant", "scan_source", "intake_summary", "track_pill", "download_output",
    "next_step", "shape_open", "models_open", "capability_faces", "access", "ai_tools", "ide_section",
    "runners_open", "runners_check", "project_runner", "automations_open", "walkthroughs", "align_suggestions",
    "insights_dimension", "insights_window", "insights_scope", "insights_export", "review_card", "paved_roads",
    "channel_panel", "agents_strip", "channel_trace", "goal_plan", "agent_activity",
    # the data and context layer (FR-CTX1), the Knowledge graph's view of it (FR-GRV1), Destinations (FR-DST1)
    "context_pack", "context_audit", "context_health", "graph_filters", "graph_mode", "graph_focus",
    "destinations_map", "destinations_where", "destinations_investigate",
    # real projects of every shape (FR-RPJ1): what the scan step and an adopted project's page show
    "scan_cancel", "kind_not_chosen", "adopted_state", "project_areas"})

JUDGED = "a judgement made in place, beside what it judges, with its preview: Take me there opens it"
IT_ONLY = "IT's configuration, with a secret named on the server's machine: Take me there opens it"
LOCAL = "it runs in the person's own session on this machine: Take me there opens it"
CLEANUP = ("a clean-up is proposed and applied by IT or operations beside the stores it removes from, each item "
           "checked unchanged first: Take me there opens the Data and context page")
DELIVERY = ("a delivery or a publication is signed beside the environment's state and IT's deploy gate; Ask Rihma's "
            "\"where is this running?\" (kernel/destinations_cli.py chat_answer) takes the person there")
FOLDERS = ("a folder the cockpit may read is allowed by IT, or by a single operator after saying yes, beside the "
           "folder refused: Take me there opens it")
OWN_CODE = ("it runs the project's own code on this machine after the person's yes, beside the stated command: Take "
            "me there opens it")
PRESETS = ("a saved view names the filters set beside it; Ask Rihma opens the graph with filters read from the words "
           "(kernel/graph_assist.py open_answer), and Take me there saves them")

CHAT: dict[str, tuple[str, str]] = {
    "pause": ("action", "pause"), "resume": ("action", "resume"), "answer": ("action", "answer_question"),
    "assume": ("action", "let_rihma_assume"), "decide": ("action", "decide"), "report": ("action", "report_change"),
    "comment": ("action", "comment"), "customize": ("action", "layout_edit"), "theme": ("action", "theme"),
    "density": ("action", "theme"), "create_embed": ("action", "create_embed"),
    "validate_concept": ("action", "decide"), "runners_decide": ("action", "decide"),
    "insights_pin": ("action", "layout_edit"),
    "adopt_project": ("walk", "plug_in"), "confidential": ("walk", "plug_in"), "new_project": ("walk", "new_idea"),
    "add_material": ("walk", "documents"), "models_set": ("walk", "model"), "models_test": ("walk", "model"),
    "models_remove": ("walk", "model"), "models_private": ("walk", "model"), "models_preset": ("walk", "model"),
    "models_use_claude": ("walk", "model"), "models_use_codex": ("walk", "model"),
    "models_use_opencode": ("walk", "model"), "walk_plug_in": ("walk", "plug_in"),
    "walk_new_idea": ("walk", "new_idea"), "walk_documents": ("walk", "documents"), "walk_model": ("walk", "model"),
    "walk_tour": ("walk", "tour"),
    "ide_setup": ("goal", "handoff"), "handoff": ("goal", "handoff"), "integrations": ("goal", "connect"),
    "automations_template": ("goal", "schedule"),
    "shape_start": ("chat", "kernel.shape:start"), "shape_say": ("chat", "kernel.shape:say"),
    "shape_attach": ("chat", "kernel.shape:attach"), "shape_draft": ("chat", "kernel.shape:edit_draft"),
    "shape_create": ("chat", "kernel.shape:create"), "channel_post": ("chat", "kernel.channel_rihma:reply"),
    "setup_checklist": ("chat", "kernel.setup_chat:setup_answer"),
    "automations_suggest": ("chat", "kernel.setup_chat:suggest_answer"),
    "archived_projects": ("chat", "kernel.setup_chat:duplicates_answer"),
    "log_signal": ("op", "log_signal"), "build_pack": ("op", "build_pack"), "build_output": ("op", "build_outputs"),
    "build_outputs": ("op", "build_outputs"), "autopilot_stop": ("op", "stop_autopilot"),
    "run_assessment": ("op", "run_assessment"), "automations_new": ("op", "add_automation"),
    "automations_save": ("op", "add_automation"), "automations_describe": ("op", "add_automation"),
    "automations_run": ("op", "run_automation"), "automations_dry_run": ("op", "dry_run_automation"),
    "automations_pause": ("op", "pause_automation"), "automations_resume": ("op", "resume_automation"),
    "automations_remove": ("op", "remove_automation"), "automations_tags": ("op", "set_tags"),
    "health_run": ("op", "run_check"), "health_enable": ("op", "enable_check"),
    "health_disable": ("op", "disable_check"), "health_enable_all": ("op", "enable_check"),
    "align_scan": ("op", "align_scan"), "mark_all_reviewed": ("op", "review_done"),
    "channel_pause": ("op", "pause_channel"), "setup_do": ("op", "setup_step"),
    "automations_suggest_accept": ("op", "accept_suggestion"),
    "automations_suggest_dismiss": ("op", "dismiss_suggestion"), "archive_project": ("op", "archive_project"),
    "restore_project": ("op", "restore_project"), "remove_project": ("op", "remove_project"),
    "export_evidence": ("open", "the evidence pack is a file to download: Take me there opens the Evidence view"),
    "autonomy": ("open", "the autonomy cap is a compliance judgement with a reason: " + JUDGED),
    "track_settings": ("open", JUDGED), "checkpoint_look": ("open", JUDGED), "autopilot_start": ("open", JUDGED),
    "revoke_delegation": ("open", JUDGED), "choose_outputs": ("open", JUDGED), "modules": ("open", JUDGED),
    "revoke_embed": ("open", JUDGED), "project_settings": ("open", JUDGED), "rewind_project": ("open", JUDGED),
    "go_ahead": ("open", JUDGED), "build_without_waiting": ("open", JUDGED), "posture": ("open", JUDGED),
    "assessment_changes": ("open", JUDGED), "runners_set": ("open", JUDGED), "automations_edit": ("open", JUDGED),
    "align_decide": ("open", JUDGED), "align_bulk": ("open", JUDGED), "review_mark": ("open", JUDGED),
    "review_digest": ("open", JUDGED), "choose_road": ("open", JUDGED), "channel_settle": ("open", JUDGED),
    "configure_gcp_road": ("open", IT_ONLY), "drive_connector": ("open", IT_ONLY),
    "console_run": ("open", LOCAL), "console_gnomon": ("open", LOCAL), "console_stop": ("open", LOCAL),
    "console_terminal": ("open", LOCAL), "console_settings": ("open", LOCAL),
    # FR-CTX1, FR-GRV1, FR-DST1
    "data_cleanup": ("open", CLEANUP), "data_apply": ("open", CLEANUP), "graph_presets": ("open", PRESETS),
    "graph_pin": ("action", "layout_edit"), "destinations_check": ("op", "check_destinations"),
    "destinations_deliver": ("open", DELIVERY), "destinations_promote": ("open", DELIVERY),
    "destinations_publish": ("open", DELIVERY),
    # FR-RPJ1: the scan step's choices are the plug-in walkthrough's; an adopted project's watch is an operation
    "adopt_again": ("walk", "plug_in"), "adopt_take": ("walk", "plug_in"), "adopt_workspace": ("walk", "plug_in"),
    "adopt_usage": ("walk", "plug_in"), "scan_track": ("walk", "plug_in"), "use_local_model": ("walk", "model"),
    "allow_root": ("open", FOLDERS), "allow_folder": ("open", FOLDERS), "baseline_stated": ("open", OWN_CODE),
    "watch_setup": ("op", "set_watch"),
}

# Every assistant action, and the control that does it by hand (``act``: each operation's own, in its table).
ACTION_CONTROLS = {"open": "palette", "answer_question": "answer", "let_rihma_assume": "assume", "decide": "decide",
                   "pause": "pause", "resume": "resume", "report_change": "report", "comment": "comment",
                   "layout_edit": "customize", "theme": "theme", "create_embed": "create_embed", "act": "setup_do"}

IT_CLI = "IT's configuration, with secrets named in the server's environment: kept on IT's command line"
FILES = "it writes files into a folder on the operator's machine; the cockpit offers the same as downloads"
TERMINAL = "it works in a terminal on the operator's machine (docs/brownfield.md)"

# Every signed command of the command line: its cockpit route, or ("", why not).
CLI_ROUTES: dict[str, str] = {
    "adopt": "post_adopt", "align": "post_repo_alignment_decide", "answer": "post_answer", "assess": "post_assessment",
    "assessment change": "post_assessment_changes", "assume": "post_assume",
    "automations accept": "post_suggestion_accept", "automations add": "post_automation",
    "automations describe": "post_automation_compose", "automations dismiss": "post_suggestion_dismiss",
    "automations edit": "put_automation", "automations pause": "post_automation_pause",
    "automations remove": "post_automation_remove", "automations resume": "post_automation_resume",
    "automations run-now": "post_automation_run", "automations tag": "put_project_tags", "autonomy set": "put_autonomy",
    "autopilot start": "post_autopilot_start", "autopilot stop": "post_autopilot_stop", "change": "post_change",
    "channel post": "post_channel", "checks disable": "post_check_disable", "checks enable": "post_check_enable",
    "checks run": "post_check_run", "concept edit": "post_concept_edit", "console": "post_console_run",
    "decide": "post_decide", "delegation grant": "post_autopilot_start", "delegation revoke": "post_delegation_revoke",
    "embed create": "post_embed", "embed revoke": "post_embed_revoke", "evidence": "post_evidence_export",
    "material add": "post_material", "models remove": "post_model_remove", "models set": "put_model",
    "models use": "post_models_use", "modules set": "put_modules", "new": "post_project", "output": "put_outputs",
    "pack": "post_pack_build", "posture confirm": "put_posture", "posture set": "put_posture",
    "project archive": "post_project_archive", "project remove": "post_project_remove",
    "project restore": "post_project_restore", "repo gate": "post_check_run", "review": "post_review_mark",
    "rewind": "post_rewind", "road choose": "put_project_road", "road configure": "put_road",
    "runners set": "put_runner", "settings": "put_settings", "setup": "post_project_setup", "shape": "post_shape",
    "shape attach": "post_shape_attach", "shape create": "post_shape_create", "shape edit": "put_shape_draft",
    "shape say": "post_shape_say", "shape start": "post_shape", "shell": "post_console_terminal",
    "signal log": "post_signal", "tracking look": "post_checkpoint_look", "tracking set": "put_tracking",
    "walkthrough": "post_walkthrough", "workspace open": "post_handoff", "intake": "post_project",
    "baseline": "post_baseline_stated", "data cleanup": "post_data_cleanup", "data apply": "post_data_apply",
    "destinations": "post_destinations_check", "publish": "post_publish",
}
CLI_WHY_NOT: dict[str, str] = {
    "autopilot relay": IT_CLI, "connector disable": IT_CLI, "connector enable": IT_CLI, "hooks add": IT_CLI,
    "hooks bind": IT_CLI, "hooks remove": IT_CLI, "relay cockpit": IT_CLI, "relay subscribe": IT_CLI,
    "relay unsubscribe": IT_CLI, "tracking digest": IT_CLI, "contract export": FILES, "repo releases": FILES,
    "repo attach": TERMINAL, "repo contract": TERMINAL, "repo holdouts": TERMINAL, "repo scan": TERMINAL,
    "workspace submit": TERMINAL,
    "road rollback": "a rollback is operations' act from their terminal, after the incident card (kernel/operate.py)",
    "security accept": "a risk is accepted with an expiry by IT from the scan's own report; the cockpit shows it",
    "security ingest": "a SARIF file is ingested from the scanner's output on the operator's machine",
    "inputs refine": "the intake summary is read in the cockpit; asking a model to refine it is a terminal step",
    "integration declare": "a data integration is declared as a change in the Plan's Data integrations (a change "
                           "request, post_change); the command records it directly for IT",
    "integration withdraw": "withdrawn as a change in the Plan's Data integrations (post_change), as declared",
}

# The stable line's controls (assessment priorities and progress, jobs, the Inbox's batches, understanding, the folder
# picker, guided journeys, capsules and scope): reads, or the chat path that does the same.
READS = READS | frozenset({
    "assessment_progress", "assessment_progress_card", "scan_progress", "journey_next", "journey_starters",
    "journey_guide", "scope_switch", "capsules", "square_scope", "assistant_scope", "job_ask", "assessment_ask",
    "pick_browse", "pick_here"})
GUIDE = "the guide's own record, kept in the guided panel of Ask Rihma itself"
CHAT.update({
    "cancel_assessment": ("open", "a running assessment is cancelled beside its live progress: Take me there opens it"),
    "inbox_batch_decide": ("action", "decide"), "inbox_batch_assume": ("action", "let_rihma_assume"),
    "understood_correct": ("walk", "documents"), "customize_view": ("action", "layout_edit"),
    "customize_tabs": ("action", "layout_edit"),
    "journey_do": ("open", "a step is done through its own route, which has its own chat path: Take me there opens it"),
    "journey_did": ("open", GUIDE), "journey_skip": ("open", GUIDE), "journey_stop": ("open", GUIDE)})
