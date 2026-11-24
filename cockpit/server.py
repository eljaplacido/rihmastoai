"""The Rihma cockpit server: the page and a JSON API over the kernel, on loopback only (FR-T1, FR-M6).

Besides the canon and the Inbox it serves the read models people decide with: a change's impact
before it is decided (FR-P5), the canon's alignment findings (FR-S6), the Cell and Floor
projections of Gnomon's runs (FR-M3), and where a project stands (``kernel.status``): each
criterion's evidence, verified or only claimed (FR-O6); a one-line "now" with its state; the
project's health with its reasons and forecast (FR-T1); what its running cell is doing, read from
Gnomon's own audit trail (FR-T1); and the checklist people try a release with (FR-R1). Showing
them changes nothing.

It also carries three writes the kernel signs and checks like any decision: editing a requirement
of a plan that waits on approval (``kernel.plan``, FR-P7), and pausing and resuming a project at
its next safe point (``kernel.safestop``, FR-J3).

The redesigned cockpit adds: every dashboard widget's read model in one answer (FR-T1-AC-11), a
layout per person, persona and lens kept in the factory home's ``_cockpit/layouts/`` and never in
a project ledger, a project's lens and stage-ordered views (FR-T1-AC-12), comments (FR-T1-AC-13),
the delivery square's signals and concepts, the capability catalogue, embeds, the autonomy cap,
capability packs and evidence exports downloaded once (FR-T1-AC-15), and the assistant, whose
answers and proposals are checked by the kernel and which writes nothing (FR-V1-AC-5). Reading a
capability pack shows the one last written and never builds one; building is its own signed POST
(FR-T1-AC-16). An embed's snippet points at the embed server (``--embed-base`` or
``RIHMA_EMBED_BASE``), never at this server, which serves no widget (FR-I1-AC-4).

Start it on the machine that runs the kernel (for example a GPU box) and reach it from a workstation
through an SSH tunnel:

    python -m cockpit.server --home var --port 8787
    ssh -L 8787:127.0.0.1:8787 gpu-box     # then open the printed link

Sign-in works like Gnomon's dashboard. At start the server prints one link,
``http://127.0.0.1:<port>/#k=<bootstrap>``. The page posts the bootstrap to ``/auth`` once and
gets a session token, which it keeps in sessionStorage. The bootstrap cannot be used twice.

Rules the server keeps:
- it binds to 127.0.0.1 and refuses any other address;
- every ``/api/*`` request needs ``Authorization: Bearer <token>``;
- every POST also needs an ``Origin`` equal to the server's own origin, and a ``Host`` of
  ``127.0.0.1:<port>`` is required on every request;
- no cookies, no CORS headers, and a Content-Security-Policy with no inline script or style;
- static files carry no data: every fact comes from the API, behind the token;
- the server never decides anything. A decision is the Inbox's: it carries the person and the
  persona who made it, and the kernel (``Canon``) accepts or refuses it.

Access (``kernel.access``, D-0016). Without an access file the cockpit is a single operator's tool,
as above: the person and persona come from the request, and the page's header says "single
operator: personas are self-declared". With ``projects/_factory/access/access.json`` in mode
``enforced`` it stays on 127.0.0.1 behind IT's identity-aware proxy, which runs beside it:
- the identity comes only from the identity provider's signed token the proxy forwards, sent once and
  verified with the provider's public keys (``kernel.access_tokens``): the cockpit holds no shared
  secret. Any other request is refused, and so is every request while the file cannot be read or checked;
- the page (``index.html``) says the mode, so an enforced page signs in through the proxy at once and
  a single operator's asks for nothing until a sign-in link is opened;
- ``/auth`` opens a session for that identity, which ends when the token it was opened with expires; the
  session travels in ``X-Rihmasto-Session`` (the token may use ``Authorization``) and answers only that
  identity;
- a run or a new project's intake starts only when the access file names an isolation runner for the
  untrusted code it runs (``kernel.access_isolation``); otherwise it is refused, and the refusal says why;
- every write route that takes a person or persona signs as the verified person (a different
  ``person`` is refused) and needs the persona granted on its project (the factory's own writes:
  on ``_factory``); the records name the identity beside the person;
- the ``Host`` and ``Origin`` the proxy forwards (the file's ``origin``) are accepted beside the
  server's own;
- a request that noticed a changed access file records it with its verified identity, and a new
  project's record carries its request's sha256, so the intake job carries out that request only.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cockpit.agent_routes import ROUTES as AGENT_ROUTES
from cockpit.agent_routes import AgentContextRoutes
from cockpit.automation_routes import ROUTES as AUTOMATION_ROUTES
from cockpit.automation_routes import UNLOCKED as AUTOMATION_UNLOCKED
from cockpit.automation_routes import AutomationRoutes, Scheduler
from cockpit.runner_routes import ROUTES as RUNNER_ROUTES
from cockpit.runner_routes import RunnerRoutes
from cockpit.shape_routes import ROUTES as CHAT_ROUTES
from cockpit.shape_routes import UNLOCKED as CHAT_UNLOCKED
from cockpit.shape_routes import ChatRoutes
from kernel import access as kaccess
from kernel import access_isolation as kisolation
from kernel import assess as kassess
from kernel import assess_cards as kassess_cards
from kernel import assistant as kassistant
from kernel import autonomy as kautonomy
from kernel import autopilot as kautopilot
from kernel import confidential as kconfidential
from kernel import dashboard as kdash
from kernel import delegation as kdelegation
from kernel import embeds as kembeds
from kernel import evidence_pack as kevidence
from kernel import input_summary as kinputs
from kernel import material as kmaterial
from kernel import outputs as koutputs
from kernel import modules as kmodules
from kernel import next_step as knext
from kernel import packs as kpacks
from kernel import plan as kplan
from kernel import posture as kposture
from kernel import profiles as kprofiles
from kernel import project_material as kadded
from kernel import project_settings as ksettings
from kernel import rewind as krewind
from kernel import signals as ksignals
from kernel import source_guard as ksource
from kernel import track as ktrack
from kernel.canon import CARD_DECIDERS, CARD_VERDICTS, PERSPECTIVES, Canon, DecisionRefused, deciders_of
from kernel.change import CLASSES, NEEDS_DECISION, WAY_BACK, submit, triage
from kernel.insight import alignment, change_impact, impact
from kernel.intake import MATURITY_MEANING, render_brief
from kernel.learn import FACTORY_PID, factory_project, immune_memory, model_reliability
from kernel.lenses import LENSES, lens_for, project_context
from kernel.observations import TRIGGERS, apply_updates, observations
from kernel.people import PERSONAS, Identity, is_person
from kernel.pricing import load_prices
from kernel.projections import cell, floor
from kernel.safestop import MAY_PAUSE, request_pause, resume
from kernel.spec import KINDS as CRITERION_KINDS
from kernel.status import evidence, health, live, now, try_it
from kernel.store import (
    HOME_ENV,
    MATURITIES,
    MODES,
    REPO_ROOT,
    STAGES,
    Factory,
    Project,
    read_json,
    write_json,
    write_text,
)

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8787
STATIC_DIR = Path(__file__).resolve().parent / "static"
# The page's own files: a flat folder of HTML, scripts (ES modules), stylesheets and the logo's
# PNG images. A name is served only when it has one of these extensions and exists in that folder;
# nothing else is.
STATIC_EXT = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
}
_STATIC_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\.(?:html|js|css|png)\Z")
MAX_BODY = 1 << 20
SESSION_TTL = 12 * 3600      # seconds a session lives after its last use
LINK_TTL = 600               # seconds an extra sign-in link stays valid
LOG_TAIL_LINES = 20
RECENT_EVENTS = 50

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}

# Labels and the "Cockpit by persona" table of docs/v1-design.md.
PERSONA_INFO = {
    "business_owner": ("Business owner", "goal, benefit against the baseline, decisions waiting, stale approvals",
                       "decide, accept, change priority, request a change"),
    "product_owner": ("Product owner", "brief, spec, questions, changes and decisions waiting",
                      "approve, accept a validation, decide a change, answer questions, request a change"),
    "concept_evaluator": ("Concept evaluator", "brief, opinions, assumptions due, spec",
                          "answer, let the factory assume, challenge an assumption"),
    "end_user": ("End-user tester", "what to try, the validation build, their own reports",
                 "report an observation (UI gap, requirement, data, defect)"),
    "it": ("IT / partner", "paved roads, deploy gates, environment drift, IT rules",
           "configure a road, approve or refuse a deploy, file an infra change"),
    "developer": ("Developer", "tasks and gate signals, the Cell (every Gnomon run), escalations",
                  "answer escalations, approve gates within the autonomy rules"),
    "operations": ("Operations", "Pulse (probes, service levels, shadow and canary), incidents",
                   "acknowledge, roll back, open a defect"),
    "stakeholder": ("Stakeholder", "goal, brief, questions", "answer questions, request a change"),
    "compliance": ("Compliance", "what ran, which versions, who approved, and the evidence packs",
                   "export evidence, set the autonomy cap, decide updates"),
}

# The cockpit's widget library: each widget answers one question from one read model of
# GET /api/dashboard. A layout may only name these (the assistant reshapes within them too).
WIDGETS = {
    "kpi_strip": ("Key figures", "gauge", "How is the factory doing at a glance?"),
    "square": ("Delivery square", "square", "Where is everything in the delivery square?"),
    "pipeline": ("Pipeline", "pipeline", "Where is the work?"),
    "decisions": ("Decisions waiting", "inbox", "What waits on me?"),
    "catalogue": ("Capabilities", "catalogue", "Which capabilities do we have?"),
    "live": ("Live agents", "pulse", "What are agents doing now?"),
    "timeline": ("Task timeline", "timeline", "Where did the time go?"),
    "gate_trend": ("Gate trend", "gate", "Is the factory getting the work right?"),
    "coverage": ("Evidence coverage", "file-check", "How much is proven rather than claimed?"),
    "activity": ("Activity", "activity", "What just happened, and who did it?"),
    "models": ("Builder models", "cpu", "Which models do the work well?"),
    "health": ("Project health", "heart", "Which projects are on track?"),
    "updates": ("Updates", "bell", "What changed outside, and what should we try?"),
    "autonomy": ("Autonomy", "gauge", "How far may the factory act alone?"),
    "evidence_packs": ("Evidence packs", "file-check", "Can we show it was checked?"),
    "spend": ("Spend", "coins", "What does the work cost?"),
    "feed_health": ("Feed health", "plug", "Are the integration feeds fresh?"),
    "eval_trend": ("Eval trend", "flask", "Do the evals still hold?"),
    "try_it": ("Try it", "play", "What can people try right now?"),
    "track": ("Staying on track", "flag", "Is each project on track against its approved plan?"),
}
# Read-only presets per lens; a person's first edit duplicates one into a personal layout.
LENS_DEFAULTS = {
    "business": [("kpi_strip", "L"), ("decisions", "M"), ("catalogue", "M"), ("square", "L"), ("track", "M"),
                 ("health", "M"), ("activity", "M")],
    "concept": [("decisions", "M"), ("square", "M"), ("coverage", "M"), ("pipeline", "M")],
    "delivery": [("live", "M"), ("gate_trend", "M"), ("timeline", "L"), ("decisions", "M"), ("activity", "M")],
    "operations": [("health", "M"), ("track", "M"), ("updates", "M"), ("decisions", "M"), ("activity", "M"),
                   ("spend", "L")],
    "compliance": [("evidence_packs", "L"), ("autonomy", "M"), ("coverage", "M"), ("activity", "M"), ("updates", "M")],
    "insight": [("kpi_strip", "L"), ("gate_trend", "M"), ("models", "M"), ("coverage", "M"), ("spend", "M"),
                ("pipeline", "L")],
}
# The view a preset shows first: a list where the widget is a list of things, else its chart.
LIST_FIRST = {"decisions", "catalogue", "live", "activity", "health", "updates", "evidence_packs", "try_it", "track"}
MAX_WIDGETS = 24
LAYOUT_VIEWS = ("chart", "table", "list")
EXPORT_TTL = 600             # seconds a one-time download link stays valid
PROMOTERS = ("product_owner", "business_owner")   # kernel/canon.py promote_comment
# Who builds a capability pack from the cockpit: the people who export evidence. Building records a
# new version (packs.json and the ledger) when the content changed, so it is a signed write.
PACK_BUILDERS = tuple(kevidence.EXPORTERS)
SIGNAL_ID = r"(?P<sid>S-\d{1,9})"
CARD_ID = r"(?P<cid>C-\d{1,9})"

MODE_MEANING = {
    "socratic": "every question goes to a person; nothing is assumed",
    "assume": "the factory answers each question itself, as an assumption with a due date",
    "mixed": "blocking questions go to a person and the rest are assumed (the default)",
}

# The factory's own canon (kernel/learn.py) is shown under the factory's name.
FACTORY_TITLE = "Rihma itself"
# A concept card's title as kernel/signals.py writes it; the title a person edits lives in its payload.
CONCEPT_PREFIX = "Validate as a concept? "
# The square lists every signal still new, and the newest of the others up to this many.
SQUARE_SIGNALS = 50
# ... and up to this many signals the page names (?show=), such as one just triaged that is no longer
# new and not among the newest, so the person sees what it became.
SQUARE_SHOWN = 20
SIGNAL_ID_RE = re.compile(r"S-\d{1,9}\Z")

# Four bands over the seven stages, for readers who do not think in stages (FR-T1-AC-3).
BANDS = (("decide", "Decide", (1, 2)), ("shape", "Shape", (3, 4)), ("deliver", "Deliver", (5, 6)),
         ("run", "Run", (7,)))
# The last stage each maturity runs ("Maturity levels" in docs/v1-design.md).
MATURITY_LAST_STAGE = {"explore": 4, "demo": 5, "pilot": 6, "production": 7}

_REQ_ID = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\Z")
# A requirement id in a path: R-2, or a customer's own id such as FR-P7 (kept by kernel/spec.py).
RID = r"(?P<rid>[A-Z][A-Z0-9]{0,15}(?:-[A-Z0-9]{1,15}){1,6})"
MAX_CRITERIA = 40

# The evidence states of kernel.status.evidence, strongest first (FR-O6).
EVIDENCE_STATES = ("verified", "held_out", "claimed", "failing", "not_measured")

# Who acted on a ledger event. People own intent and decisions; agents are their delegates: a model
# in a role, or the kernel's own rule. The model is shown where the ledger records one.
AGENT_ROLE = {
    "intake_done": "analyst", "question_added": "analyst", "opinion_added": "analyst", "spec_written": "analyst",
    "holdouts_authored": "holdout author", "cell_ran": "builder", "input_refined": "analyst",
}
PERSON_KEYS = ("person", "by", "chosen_by", "stopped_by", "accepted_as_is_by")

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"
ROUTES = [
    ("GET", r"/api/meta", "get_meta"),
    ("GET", r"/api/personas", "get_personas"),
    ("GET", r"/api/projects", "get_projects"),
    ("GET", rf"/api/projects/{PID}", "get_project"),
    ("GET", rf"/api/projects/{PID}/inbox", "get_inbox"),
    ("GET", rf"/api/projects/{PID}/impact", "get_impact"),
    ("GET", rf"/api/projects/{PID}/alignment", "get_alignment"),
    ("GET", rf"/api/projects/{PID}/cell", "get_cell"),
    ("GET", rf"/api/projects/{PID}/evidence", "get_evidence"),
    ("GET", rf"/api/projects/{PID}/now", "get_now"),
    ("GET", rf"/api/projects/{PID}/health", "get_health"),
    ("GET", rf"/api/projects/{PID}/plan", "get_plan"),
    ("GET", rf"/api/projects/{PID}/live", "get_live"),
    ("GET", rf"/api/projects/{PID}/try", "get_try"),
    ("GET", r"/api/floor", "get_floor"),
    ("GET", r"/api/jobs", "get_jobs"),
    # the dashboard, the delivery square, the catalogue and the capability layer
    ("GET", r"/api/dashboard", "get_dashboard"),
    ("GET", r"/api/catalogue", "get_catalogue"),
    ("GET", r"/api/square", "get_square"),
    ("GET", r"/api/signals", "get_signals"),
    ("GET", r"/api/profiles", "get_profiles"),
    ("GET", r"/api/inbox", "get_inbox_all"),
    ("GET", r"/api/ui-map", "get_ui_map"),
    ("GET", r"/api/layout", "get_layout"),
    ("GET", r"/api/autonomy", "get_autonomy"),
    ("GET", r"/api/postures", "get_postures"),
    ("GET", rf"/api/projects/{PID}/posture", "get_posture"),
    ("GET", r"/api/embeds", "get_embeds"),
    ("GET", r"/api/exports/(?P<token>[A-Za-z0-9_-]{16,64})", "get_export"),
    ("GET", rf"/api/projects/{PID}/timeline", "get_timeline"),
    ("GET", rf"/api/projects/{PID}/context", "get_context"),
    ("GET", rf"/api/projects/{PID}/comments", "get_comments"),
    ("GET", rf"/api/projects/{PID}/pack", "get_pack"),
    ("GET", rf"/api/projects/{PID}/attestation", "get_attestation"),
    ("GET", rf"/api/projects/{PID}/outputs", "get_outputs"),
    ("PUT", rf"/api/projects/{PID}/outputs", "put_outputs"),
    ("POST", rf"/api/projects/{PID}/outputs/build", "post_outputs_build"),
    ("GET", rf"/api/projects/{PID}/assessment", "get_assessment"),
    ("POST", r"/api/signals", "post_signal"),
    ("POST", rf"/api/signals/{SIGNAL_ID}/triage", "post_signal_triage"),
    ("POST", rf"/api/concepts/{CARD_ID}/edit", "post_concept_edit"),
    ("POST", r"/api/profiles/propose", "post_profile_propose"),
    ("POST", r"/api/postures/preview", "post_posture_preview"),
    ("POST", r"/api/assistant", "post_assistant"),
    ("POST", r"/api/embeds", "post_embed"),
    ("POST", r"/api/embeds/(?P<eid>E-\d{1,9})/revoke", "post_embed_revoke"),
    ("POST", rf"/api/projects/{PID}/comments", "post_comment"),
    ("POST", rf"/api/projects/{PID}/comments/(?P<cmid>CM-\d{{1,9}})/promote", "post_comment_promote"),
    ("POST", rf"/api/projects/{PID}/evidence", "post_evidence_export"),
    ("POST", rf"/api/projects/{PID}/pack/build", "post_pack_build"),
    ("POST", rf"/api/projects/{PID}/assessment", "post_assessment"),
    ("POST", rf"/api/projects/{PID}/assessment/changes", "post_assessment_changes"),
    ("PUT", r"/api/layout", "put_layout"),
    ("PUT", r"/api/autonomy", "put_autonomy"),
    ("PUT", rf"/api/projects/{PID}/autonomy", "put_project_autonomy"),
    ("GET", r"/api/modules", "get_modules"),      # the parts of Rihmasto in use (kernel/modules.py)
    ("PUT", r"/api/modules", "put_modules"),
    ("PUT", rf"/api/projects/{PID}/modules", "put_project_modules"),
    ("PUT", rf"/api/projects/{PID}/posture", "put_posture"),
    ("POST", r"/api/projects", "post_project"),
    ("POST", r"/api/adopt", "post_adopt"),
    ("POST", r"/api/source/preview", "post_source_preview"),   # a folder's material map; records nothing
    ("POST", rf"/api/projects/{PID}/cards/(?P<cid>C-\d{{1,9}})/decide", "post_decide"),
    ("POST", rf"/api/projects/{PID}/questions/(?P<qid>Q-\d{{1,9}})/answer", "post_answer"),
    ("POST", rf"/api/projects/{PID}/questions/(?P<qid>Q-\d{{1,9}})/assume", "post_assume"),
    ("POST", rf"/api/projects/{PID}/assumptions/(?P<aid>A-\d{{1,9}})/settle", "post_settle"),
    ("POST", rf"/api/projects/{PID}/changes", "post_change"),
    ("POST", rf"/api/projects/{PID}/advance", "post_advance"),
    ("POST", rf"/api/projects/{PID}/plan/requirements/{RID}", "post_plan_requirement"),
    ("POST", rf"/api/projects/{PID}/pause", "post_pause"),
    ("POST", rf"/api/projects/{PID}/resume", "post_resume"),
    # change anything set at creation, go back a step, add material (FR-CHG1)
    ("PUT", rf"/api/projects/{PID}/settings", "put_settings"),
    ("POST", rf"/api/projects/{PID}/settings/preview", "post_settings_preview"),
    ("POST", rf"/api/projects/{PID}/rewind", "post_rewind"),
    ("POST", rf"/api/projects/{PID}/material", "post_material"),
    ("GET", rf"/api/projects/{PID}/track", "get_track"),
    ("PUT", rf"/api/projects/{PID}/tracking", "put_tracking"),
    ("POST", rf"/api/projects/{PID}/checkpoints/(?P<stage>[2-7])/look", "post_checkpoint_look"),
    ("POST", rf"/api/projects/{PID}/autopilot", "post_autopilot_start"),
    ("POST", rf"/api/projects/{PID}/autopilot/stop", "post_autopilot_stop"),
    ("POST", rf"/api/projects/{PID}/delegations/(?P<did>DL-\d{{1,9}})/revoke", "post_delegation_revoke"),
    ("POST", r"/api/links", "post_link"),
]
ROUTES = [(m, re.compile(p + r"/?\Z"), name)    # chat, Models; AI tools, IDE (FR-AGC1); Runners; FR-AUT1
          for m, p, name in ROUTES + CHAT_ROUTES + AGENT_ROUTES + RUNNER_ROUTES + AUTOMATION_ROUTES]
# Writes that record nothing (the assistant only proposes; a profile proposal is a rule over text).
# They run outside the write lock, so a slow model call never holds up a decision. An assessment
# reads a whole repository and keeps its records under their own file locks (kernel/assess.py): it
# runs outside the write lock too, and touches no card.
UNLOCKED = {"post_assistant", "post_profile_propose", "post_source_preview", "post_posture_preview", "post_assessment",
            *CHAT_UNLOCKED, *AUTOMATION_UNLOCKED}


class FileResponse:
    """A file the API hands over as a download (an exported evidence pack), never as JSON."""

    def __init__(self, path: Path, ctype: str = "application/zip"):
        self.path = Path(path)
        self.ctype = ctype


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# -- background jobs ------------------------------------------------------------------------------

class SubprocessRunner:
    """Runs ``python <args>`` from the repository root as a child process, never through a shell.

    The child gets the factory home in ``GNOMONFACTORY_HOME`` and writes its output to the log.
    """

    def __init__(self, home: str | Path):
        self.home = Path(home)
        self._procs: dict = {}
        self._lock = threading.Lock()
        self._n = 0

    def start(self, args: list, log_path) -> str:
        if isinstance(args, (str, bytes)) or not all(isinstance(a, str) for a in args):
            raise TypeError("args must be a list of strings, never a shell string")
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env[HOME_ENV] = str(self.home)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        with open(log_path, "ab") as log:
            proc = subprocess.Popen([sys.executable, *args], cwd=str(REPO_ROOT), stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, env=env, shell=False)
        with self._lock:
            self._n += 1
            job_id = f"J-{self._n:04d}-{proc.pid}"
            self._procs[job_id] = proc
        return job_id

    def status(self, job_id: str) -> dict:
        with self._lock:
            proc = self._procs.get(job_id)
        if proc is None:
            return {"state": "unknown", "code": None}
        code = proc.poll()
        if code is None:
            return {"state": "running", "code": None}
        return {"state": "done" if code == 0 else "failed", "code": code}


# -- the server -----------------------------------------------------------------------------------

class CockpitServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR would let another socket take the same port.
    allow_reuse_address = os.name != "nt"

    def __init__(self, factory: Factory, port: int, runner=None, assistant_model=None,
                 embed_base: str | None = None):
        self.factory = factory
        self.runner = runner if runner is not None else SubprocessRunner(factory.home)
        # The assistant's model (kernel.model.Model), or None: then it answers from the cockpit map.
        self.assistant_model = assistant_model
        # Shape it in chat's model (the analyst role), or None: then the chat says no model is set up.
        self.shape_model = None
        # Where websites reach the embed server: an embed's snippet points there, never at the cockpit.
        self.embed_base = kembeds.embed_base(embed_base)
        self.quiet = True
        self.write_lock = threading.RLock()
        self._auth_lock = threading.Lock()
        self._heads_lock = threading.Lock()
        self._jobs_lock = threading.Lock()
        self._links: dict = {}       # bootstrap -> expiry (monotonic seconds) or None
        self._sessions: dict = {}    # token -> expiry (monotonic seconds)
        self._session_ids: dict = {}  # token -> (the verified identity it was opened for, its token's expiry)
        self._downloads: dict = {}   # one-time token -> (file name in exports, expiry)
        self.jobs: list = []
        self.assessing: dict = {}    # pid -> the assessment running in the background, or how it ended
        # The cockpit's own files, never in a project's ledger: layouts per person, and exports.
        self.cockpit_dir = factory.home / "_cockpit"
        self.layouts_dir = self.cockpit_dir / "layouts"
        self.exports_dir = self.cockpit_dir / "exports"
        super().__init__((LOOPBACK, int(port)), CockpitHandler)
        host, real_port = self.server_address[:2]
        if host != LOOPBACK:
            self.server_close()
            raise RuntimeError(f"the cockpit bound to {host}, not {LOOPBACK}")
        self.port = real_port
        self.origin = f"http://{LOOPBACK}:{real_port}"
        self.host_header = f"{LOOPBACK}:{real_port}"
        # One trusted HTTPS front (tailscale serve, a company reverse proxy) may reach the loopback cockpit:
        # its Host and Origin are accepted beside the loopback ones (--public-origin; FR-T1-AC-2).
        self.public_origin: str | None = None
        if self.embed_base is not None and _origin_of(self.embed_base) == self.origin:
            self.server_close()
            raise ValueError("the embed base names this cockpit; it must name the embed server "
                             "(python -m embed.server)")
        self.heads_path = factory.home / "cockpit" / "heads.json"
        self.jobs_dir = factory.home / "jobs"

    # sign-in

    def issue_link(self, ttl: float | None = LINK_TTL) -> str:
        """A one-use bootstrap. The link printed at start has no expiry; extra links expire."""
        bootstrap = secrets.token_urlsafe(32)
        with self._auth_lock:
            self._links[bootstrap] = None if ttl is None else time.monotonic() + ttl
        return bootstrap

    def redeem(self, bootstrap) -> str | None:
        """Exchange a bootstrap for a session token, once."""
        if not isinstance(bootstrap, str) or not bootstrap:
            return None
        now = time.monotonic()
        with self._auth_lock:
            match = next((k for k in self._links if hmac.compare_digest(k, bootstrap)), None)
            if match is None:
                return None
            expiry = self._links.pop(match)
            if expiry is not None and expiry < now:
                return None
            token = secrets.token_urlsafe(32)
            self._sessions[token] = now + SESSION_TTL
            return token

    def open_session(self, identity: str, until: float | None = None) -> str:
        """A session for a verified identity (enforced access): the proxy's sign-in replaces the bootstrap.
        The session answers that identity only, and ends at ``until`` (wall-clock seconds), when the
        signed token it was opened with expires."""
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._auth_lock:
            self._sessions[token] = now + SESSION_TTL
            self._session_ids[token] = (identity, None if until is None else now + (until - time.time()))
        return token

    # one-time downloads (an exported evidence pack), served only from the exports folder

    def offer_download(self, name: str) -> str:
        token = secrets.token_urlsafe(24)
        with self._auth_lock:
            self._downloads[token] = (name, time.monotonic() + EXPORT_TTL)
        return token

    def take_download(self, token: str) -> Path | None:
        with self._auth_lock:
            match = next((k for k in self._downloads if hmac.compare_digest(k, token)), None)
            if match is None:
                return None
            name, expiry = self._downloads.pop(match)
        if expiry < time.monotonic():
            return None
        folder = self.exports_dir.resolve()
        path = (folder / name).resolve()
        if path.parent != folder or not path.is_file():
            return None
        return path

    def session_ok(self, token, identity: str | None = None) -> bool:
        """A live session, opened for ``identity`` (None: a single operator's session, from a bootstrap)."""
        if not isinstance(token, str) or not token:
            return False
        now = time.monotonic()
        with self._auth_lock:
            for known in list(self._sessions):
                ends = (self._session_ids.get(known) or (None, None))[1]
                if self._sessions[known] < now or (ends is not None and ends <= now):
                    del self._sessions[known]
                    self._session_ids.pop(known, None)
            match = next((k for k in self._sessions if hmac.compare_digest(k, token)), None)
            if match is None or (self._session_ids.get(match) or (None,))[0] != identity:
                return False
            self._sessions[match] = now + SESSION_TTL
            return True

    # the ledger head the cockpit keeps (FR-L1-AC-4): truncation or a rewritten tail shows as broken

    def check_ledger(self, project) -> dict:
        store = project.ledger()
        with self._heads_lock:
            heads = read_json(self.heads_path, {}) or {}
            kept = heads.get(project.pid)
            for attempt in range(2):
                records = store.records()
                result = store.verify(head=kept)
                partial = bool(records) and not isinstance(records[-1], dict)
                if result.intact or not partial or attempt:
                    break
                time.sleep(0.05)  # a writer may be halfway through its line: read once more
            head = _head_of(records)
            if result.intact and head != kept:
                heads[project.pid] = head
                write_json(self.heads_path, heads)
        recent = []
        start = max(0, len(records) - RECENT_EVENTS)
        for i, r in enumerate(records[start:], start):
            event = r.get("event") if isinstance(r, dict) else None
            if isinstance(event, dict):
                recent.append({"seq": r.get("seq", i), "kind": event.get("kind"), "at": event.get("at"),
                               "actor": _actor(event.get("kind"), event.get("payload"))})
            else:
                recent.append({"seq": i, "kind": "(unreadable record)", "at": None})
        return {"intact": result.intact, "broken_seq": result.broken_seq, "tail_checked": result.tail_checked,
                "head": head, "kept_head": kept, "records": len(records), "recent": recent}

    # jobs

    def start_job(self, kind: str, pid: str, args: list, by: dict) -> dict:
        stamp = re.sub(r"[^0-9TZ]", "", self.factory.clock.stamp())
        log_path = self.jobs_dir / f"{stamp}-{kind}-{pid}-{secrets.token_hex(2)}.log"
        job_id = self.runner.start(list(args), log_path)
        job = {"id": job_id, "kind": kind, "project": pid, "args": list(args), "log": str(log_path),
               "started": self.factory.clock.stamp(), "by": by}
        with self._jobs_lock:
            self.jobs.append(job)
        return job

    def job_view(self, job: dict) -> dict:
        try:
            status = dict(self.runner.status(job["id"]) or {})
        except Exception as exc:  # a runner that cannot tell is "unknown", never a crash
            status = {"state": "unknown", "error": str(exc)}
        out = {k: job[k] for k in ("id", "kind", "project", "args", "started", "by")}
        out["log"] = Path(job["log"]).name
        out["state"] = status.get("state", "unknown")
        out["code"] = status.get("code")
        out["log_tail"] = _tail(Path(job["log"]), LOG_TAIL_LINES)
        if job["kind"] == "run" and out["state"] == "done":
            # The process ended; what the run itself reached is the last result it printed. A run the
            # autonomy cap stopped is not "done": it shows as capped, with the kernel's reason.
            out["outcome"] = _run_outcome(Path(job["log"]))
            if (out["outcome"] or {}).get("state") == "capped":
                out["state"] = "capped"
        if job["kind"] == "adopt" and out["state"] == "done":
            # The project an adoption made, so the Jobs page opens it: the job itself runs for the factory.
            made = (_last_result(Path(job["log"])) or {}).get("project")
            if isinstance(made, str) and Project(self.factory, made).path("project.json").exists():
                out["made"] = made
        return out

    def running_job(self, pid: str) -> dict | None:
        with self._jobs_lock:
            jobs = list(self.jobs)
        for job in jobs:
            if job["project"] == pid and self.job_view(job)["state"] == "running":
                return job
        return None

    def run_assessment(self, project: Project, run: dict, model, identity: Identity | None) -> None:
        """One assessment (kernel/assess.py) in the background, signed by whoever asked; its end, or why it
        failed, is written on ``run`` for the Assessment view."""
        try:
            with kaccess.signing(identity):
                end = {"state": "done", "id": kassess.assess(project, person=run["person"], persona=run["persona"],
                                                             model=model)["id"]}
        except Exception as exc:  # a background run's failure is shown on its view, never lost in the thread
            end = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"[:500]}
        with self._jobs_lock:
            run.update(end, ended=self.factory.clock.stamp())


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _head_of(records: list) -> dict:
    if not records:
        return {"seq": -1, "hash": None}
    last = records[-1] if isinstance(records[-1], dict) else {}
    return {"seq": last.get("seq", len(records) - 1), "hash": last.get("hash")}


def _actor(kind, payload) -> dict:
    """Who acted on one ledger event: a person (an owner, with the persona when recorded) or an agent
    (a delegate: a model role such as the builder, or the kernel), with the model where recorded."""
    payload = payload if isinstance(payload, dict) else {}
    model = payload.get("final_model") or payload.get("model")
    model = model if isinstance(model, str) and model else None
    if kind == "gnomon_run" or kind in AGENT_ROLE:
        role = payload.get("role") if kind == "gnomon_run" else AGENT_ROLE[kind]
        return {"type": "agent", "name": str(role or "agent").replace("_", " "), "model": model}
    for key in PERSON_KEYS:
        name = payload.get(key)
        if isinstance(name, str) and is_person(name):
            persona = payload.get("persona")
            return {"type": "person", "name": name, "persona": persona if persona in PERSONAS else None}
    return {"type": "agent", "name": "the kernel", "model": model}


def _tail(path: Path, lines: int) -> list:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 16384))
            data = fh.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def _last_result(path: Path) -> dict | None:
    """The indented JSON object that ends a finished job's log, or None."""
    lines = _tail(path, 400)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] != "{":
            continue
        try:
            out = json.loads("\n".join(lines[i:]))
        except ValueError:
            return None
        return out if isinstance(out, dict) else None
    return None


def _run_outcome(path: Path) -> dict | None:
    """What a finished ``kernel.cli run`` reached: the state and the reason of the result it printed last
    (an indented JSON object that ends the log). None when the log ends with no such result."""
    out = _last_result(path)
    if out is None or not isinstance(out.get("state"), str):
        return None
    return {"state": out["state"], "stage": out.get("stage"), "why": str(out.get("why") or "")[:500] or None,
            **({"material_read": True} if out.get("material_read") is True else {})}


# -- request handling -----------------------------------------------------------------------------

class CockpitHandler(BaseHTTPRequestHandler):
    server: CockpitServer
    server_version = "RihmaCockpit/1"
    sys_version = ""

    def log_message(self, fmt, *args):
        if not self.server.quiet:
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    # responses

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        body = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str, *, enforced: bool = False) -> None:
        out = {"error": message, "status": status}
        if enforced:  # the page then offers to sign in again through the organisation's proxy
            out["access"] = kaccess.ENFORCED
        self._json(status, out)

    # guards

    def _host_ok(self, access: kaccess.Access) -> bool:
        hosts = {self.server.host_header}
        if access.enforced and access.proxy is not None:
            hosts.add(urlsplit(access.proxy.origin).netloc)
        if self.server.public_origin:
            hosts.add(urlsplit(self.server.public_origin).netloc)
        if self.headers.get("Host", "") not in hosts:
            why = f"access is enforced, but {access.error}" if access.error else \
                f"open the cockpit at {self.server.origin}/"
            self._error(403, why, enforced=access.enforced)
            return False
        return True

    def _origin_ok(self, access: kaccess.Access) -> bool:
        given = self.headers.get("Origin", "")
        origins = [self.server.origin]
        if access.enforced and access.proxy is not None:
            origins.append(access.proxy.origin)
        if self.server.public_origin:
            origins.append(self.server.public_origin)
        return any(hmac.compare_digest(given, origin) for origin in origins)

    def _token_ok(self, identity: Identity | None = None) -> bool:
        """A live session for this request: with access enforced, in X-Rihmasto-Session (the proxy's token
        may use Authorization) and opened for the verified identity; else ``Authorization: Bearer``."""
        if identity is not None:
            return self.server.session_ok(self.headers.get(kaccess.SESSION_HEADER, "").strip(), identity.id)
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return self.server.session_ok(auth[len("Bearer "):].strip(), None)

    def _identity(self, access: kaccess.Access) -> Identity | None:
        """The verified identity of a request when access is enforced, else None (a single operator). A
        request that did not come through IT's proxy is refused: 401, or 403 while access cannot apply."""
        if not access.enforced:
            return None
        try:
            return kaccess.from_proxy(access, self.headers)
        except kaccess.AccessBroken as exc:
            raise ApiError(403, f"refused: {exc}") from None
        except kaccess.AccessRefused as exc:
            raise ApiError(401, f"refused: {exc}") from None

    def _asker(self, access: kaccess.Access) -> tuple[Identity | None, ApiError | None]:
        """The request's verified identity, or why it has none (refused later, after the other guards)."""
        try:
            return self._identity(access), None
        except ApiError as exc:
            return None, exc

    def _read_body(self) -> bytes | None:
        """Read the whole request body before answering, so the socket closes cleanly."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(400, "bad Content-Length")
            return None
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            self._error(413, "the request body is too large")
            return None
        return self.rfile.read(length) if length else b""

    @staticmethod
    def _parse(raw: bytes, ctype: str) -> dict:
        if not raw:
            return {}
        if ctype.split(";")[0].strip().lower() != "application/json":
            raise ApiError(415, "send JSON (Content-Type: application/json)")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "the body is not valid JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "the body must be a JSON object")
        return data

    # methods

    def do_GET(self):
        access = kaccess.load(self.server.factory)
        if not self._host_ok(access):
            return
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self._index(access)
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path.startswith("/api/"):
            try:
                identity = self._identity(access)
            except ApiError as exc:
                return self._error(exc.status, exc.message, enforced=True)
            if not self._token_ok(identity):
                return self._error(401, "sign in first: a valid session token is needed", enforced=access.enforced)
            return self._api("GET", path, {}, access, identity)
        self._error(404, "not found")

    def do_POST(self):
        self._write("POST")

    def do_PUT(self):
        self._write("PUT")

    def _write(self, method: str):
        """A POST or a PUT: the same guards (Host, Origin, bearer token, a JSON body), then the API.
        Writes run one at a time under the write lock, except those that record nothing."""
        raw = self._read_body()
        access = kaccess.load(self.server.factory)
        identity, refused = self._asker(access)
        # A write path notes a changed access file in the factory ledger before anything is decided under it,
        # with the verified identity of the request that noticed it, if the proxy vouched for one.
        kaccess.note_change(self.server.factory, access, "the cockpit", identity)
        if raw is None or not self._host_ok(access):
            return
        path = urlsplit(self.path).path
        if access.error is not None:
            return self._error(403, f"refused: access is enforced, but {access.error}: every request is refused "
                                    "until IT fixes it", enforced=True)
        if not self._origin_ok(access):
            return self._error(403, "refused: the Origin is not this cockpit")
        is_auth = path == "/auth" and method == "POST"
        if not is_auth and not path.startswith("/api/"):
            return self._error(404, "not found")
        if refused is not None:
            return self._error(refused.status, refused.message, enforced=True)
        if not is_auth and not self._token_ok(identity):
            return self._error(401, "sign in first: a valid session token is needed", enforced=access.enforced)
        try:
            body = self._parse(raw, self.headers.get("Content-Type", ""))
        except ApiError as exc:
            return self._error(exc.status, exc.message)
        if is_auth:
            return self._auth(body, identity)
        found = _route(method, path)
        if found is not None and found[1] in UNLOCKED:
            return self._api(method, path, body, access, identity)
        with self.server.write_lock:
            self._api(method, path, body, access, identity)

    def _auth(self, body: dict, identity: Identity | None) -> None:
        """A session: for the proxy's verified identity when access is enforced, else for a one-use bootstrap."""
        lasts = SESSION_TTL
        if identity is not None:
            token = self.server.open_session(identity.id, identity.expires)
            if identity.expires is not None:      # the session ends with the token it was opened with
                lasts = max(0, min(lasts, int(identity.expires - time.time())))
        else:
            token = self.server.redeem(body.get("bootstrap"))
            if token is None:
                return self._error(401, "this sign-in link was already used or is not valid")
        self._json(200, {"token": token, "expires_in": lasts})

    def _refuse_method(self):
        self._read_body()
        self._error(405, "method not allowed")

    do_DELETE = do_PATCH = do_OPTIONS = _refuse_method

    def _index(self, access: kaccess.Access) -> None:
        """The page, saying the access mode: with access enforced it signs in through the organisation's
        proxy at once; a single operator's page asks for nothing until a link is opened."""
        body = (STATIC_DIR / "index.html").read_bytes()
        if access.enforced:
            body = body.replace(b'<meta name="rihmasto-access" content="single_operator">',
                                b'<meta name="rihmasto-access" content="enforced">', 1)
        self._send(200, body, STATIC_EXT[".html"])

    def _static(self, name: str) -> None:
        if not _STATIC_NAME.match(name):
            return self._error(404, "not found")
        ctype = STATIC_EXT[name[name.rindex("."):]]
        try:
            body = (STATIC_DIR / name).read_bytes()
        except OSError:
            return self._error(404, "not found")
        self._send(200, body, ctype)

    def _api(self, method: str, path: str, body: dict, access: kaccess.Access | None = None,
             identity: Identity | None = None) -> None:
        found = _route(method, path)
        if found is None:
            allowed = any(p.match(path) for _, p, _ in ROUTES)
            return self._error(405 if allowed else 404, "method not allowed" if allowed else "not found")
        match, name = found
        query = {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}
        api = Api(self.server, access, identity)
        try:   # enforced access: the records name the identity; untrusted work goes through IT's runner
            with kaccess.signing(identity), kisolation.serving(self.server.factory):
                if method != "GET":             # a write of a module not enabled there is refused (FR-MOD2)
                    kmodules.require_route(self.server.factory, name, match.groupdict().get("pid"))
                status, out = getattr(api, name)(body=body, query=query, **match.groupdict())
        except ApiError as exc:
            return self._error(exc.status, exc.message)
        # The kernel refuses in three families. A refusal is never a 500: DecisionRefused (a
        # ValueError) and any PermissionError (AutonomyCapped, EmbedRefused, a holdout's re-authoring)
        # are a 403 with the kernel's reason; a plain ValueError is input the kernel would not take, a 400.
        except DecisionRefused as exc:
            return self._error(403, str(exc))
        except PermissionError as exc:
            return self._error(403, str(exc))
        except ValueError as exc:
            return self._error(400, str(exc))
        except Exception as exc:  # a bug, never a verdict: say so and keep serving
            traceback.print_exc()
            return self._error(500, f"internal error: {type(exc).__name__}")
        if isinstance(out, FileResponse):
            return self._file(status, out)
        self._json(status, out)

    def _file(self, status: int, out: "FileResponse") -> None:
        body = out.path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", out.ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{out.path.name}"')
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def _route(method: str, path: str):
    for m, pattern, name in ROUTES:
        match = pattern.match(path)
        if match and m == method:
            return match, name
    return None


# -- the API --------------------------------------------------------------------------------------

def _text(body: dict, key: str, *, required: bool = False, limit: int = 20000) -> str:
    value = body.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{key} must be text")
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"{key} is required")
    if len(value) > limit:
        raise ApiError(400, f"{key} is longer than {limit} characters")
    return value


def _weights_in(body: dict) -> dict | None:
    """A posture's priority weights as sent: an object of at most five names, each a whole number. The
    kernel checks the names and the range (kernel/posture.py)."""
    raw = body.get("weights")
    if raw is None:
        return None
    if not isinstance(raw, dict) or len(raw) > len(kposture.WEIGHTS) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) for k, v in raw.items()):
        raise ApiError(400, f"weights is an object of whole numbers from 0 to 3 for {', '.join(kposture.WEIGHTS)}")
    return dict(raw)


def _require_person(person: str, persona: str) -> None:
    """For writes the kernel does not check itself before recording something."""
    if not is_person(person):
        raise ApiError(403, f"refused: {person!r} is not a person; a write needs a named person")
    if persona not in PERSONAS:
        raise ApiError(403, f"refused: persona must be one of {', '.join(PERSONAS)}")


def _natural(path: Path):
    return (0, int(path.stem), "") if path.stem.isdigit() else (1, 0, path.stem)


def _count(label: str, value: int, total: int | None = None) -> dict:
    return {"label": label, "value": value, "total": total}


def _factory_label(pid: str, title):
    return FACTORY_TITLE if pid == FACTORY_PID else title


def _written_pack(project: Project) -> tuple[dict | None, dict | None]:
    """(the capability pack as last written, the latest release), read only: it never builds a pack, so
    it never records a version. ``kernel.packs.latest_pack`` reads it where the kernel has it; otherwise
    the latest release's capability-pack.json is read directly."""
    from kernel.deliver import releases

    rels = releases(project)
    latest = rels[-1] if rels else None
    reader = getattr(kpacks, "latest_pack", None)
    if callable(reader):
        pack = reader(project)
    else:
        pack = project.read(f"releases/{latest['release']}/capability-pack.json") if latest else None
    return (pack if isinstance(pack, dict) else None), latest


class Api(ChatRoutes, AgentContextRoutes, RunnerRoutes, AutomationRoutes):
    def __init__(self, server: CockpitServer, access: kaccess.Access | None = None,
                 identity: Identity | None = None):
        self.server = server
        self.factory = server.factory
        self._impacts: dict = {}     # (pid, requirement ids) -> (impact, error), for this one request
        # The access rules this request came under, and its verified identity when access is enforced.
        self.access = access if access is not None else kaccess.load(server.factory)
        self.identity = identity

    # who signs a write

    def _sign(self, person: str, persona: str, pid: str | None) -> tuple[str, str]:
        """The person and persona a write records. A single operator's are as sent; with access enforced
        they are the verified identity's name and a persona granted on ``pid`` (None: on any project),
        or the write is refused (kernel.access.sign, D-0016)."""
        if not self.access.enforced:
            return person, persona
        try:
            return kaccess.sign(self.access, self.identity, person, persona, pid)
        except kaccess.AccessRefused as exc:
            raise ApiError(403, f"refused: {exc}") from None

    def _who(self, body: dict, pid: str | None) -> tuple[str, str]:
        """The person and persona that sign a write on ``pid`` (FACTORY_PID: the factory's own records)."""
        return self._sign(_text(body, "person", limit=200), _text(body, "persona", limit=64), pid)

    # helpers

    def _project(self, pid: str):
        try:
            return self.factory.project(pid)
        except KeyError:
            raise ApiError(404, f"no project {pid}") from None

    @staticmethod
    def _read(project, name: str, default, problems: list):
        try:
            value = project.read(name, default)
        except (OSError, ValueError) as exc:
            problems.append(f"{name}: {type(exc).__name__}")
            return default
        return default if value is None else value

    @staticmethod
    def _audit(project, action: str, target: str | None, person: str, persona: str, **extra) -> None:
        """Note in the ledger that a write came through the cockpit, signed by its person and persona."""
        project.log("cockpit_write", {"action": action, "target": target, "person": person, "persona": persona,
                                      **extra})

    @staticmethod
    def _options(q: dict) -> list:
        """The question's options: up to four short answers a person can pick, the panel's proposal
        first (FR-A6). A question recorded before options existed offers its proposal alone."""
        proposed = str((q.get("opinions") or {}).get(q.get("perspective")) or "").strip()
        opts = [str(o).strip() for o in q.get("options") or [] if str(o).strip()]
        if proposed:
            opts = [proposed] + [o for o in opts if o != proposed]
        return list(dict.fromkeys(opts))[:4]

    @classmethod
    def _question_view(cls, q: dict, canon: Canon) -> dict:
        opinions = q.get("opinions") or {}
        out = dict(q)
        out["proposed"] = opinions.get(q["perspective"]) or None
        out["options"] = cls._options(q)
        out["recommended"] = out["options"][0] if out["proposed"] and out["options"] else None
        out["opinions_side_by_side"] = [{"perspective": p, "opinion": opinions.get(p), "asked": p == q["perspective"]}
                                        for p in PERSPECTIVES]
        out["card_state"] = None
        if q.get("card"):
            try:
                out["card_state"] = canon.get_card(q["card"])["state"]
            except (KeyError, ValueError, OSError):
                out["card_state"] = "missing"
        return out

    @staticmethod
    def _card_title(card: dict) -> str:
        """A card's title as people should read it. A concept's title follows the edit made to it on the
        square (its payload), so nobody validates a project under a name they do not see."""
        title = str(card.get("title") or "")
        edited = (card.get("payload") or {}).get("title") if card.get("kind") == "concept" else None
        if edited and title.startswith(CONCEPT_PREFIX):
            return CONCEPT_PREFIX + str(edited)
        return title

    def _card_view(self, card: dict, canon: Canon) -> dict:
        out = dict(card)
        out["title"] = self._card_title(card)
        out["verdicts"] = list(CARD_VERDICTS[card["kind"]])
        out["deciders"] = list(deciders_of(card))   # a card may narrow them (a posture may)
        if card["kind"] == "question" and (card.get("refs") or {}).get("question"):
            try:
                out["question"] = self._question_view(canon.question(card["refs"]["question"]), canon)
            except KeyError:
                out["question"] = None
        if card["kind"] == "change":
            out["impact"], error = self._change_impact(canon.project, card)
            if error:
                out["impact_error"] = error
        return out

    def _change_impact(self, project, card: dict):
        """Impact if changed (FR-P5): what the triaged change would touch, shown before anyone
        decides it. None until triage names requirements. Reading it records nothing."""
        tri = (card.get("payload") or {}).get("triage") or {}
        rids = tuple(sorted(set(tri.get("requirements") or [])))
        if not rids:
            return None, None
        key = (project.pid, rids)
        if key not in self._impacts:  # the impact depends on the requirements only
            try:
                self._impacts[key] = (change_impact(project, card["id"]), None)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._impacts[key] = (None, f"{type(exc).__name__}: {exc}")
        return self._impacts[key]

    @staticmethod
    def _stage_summary(meta: dict, canon: Canon, spec, contract, tasks: list, releases: list,
                       evidence_counts: dict | None = None) -> dict:
        """The seven stages with a count where one means something, grouped in four bands (FR-T1-AC-3)."""
        stage = meta.get("stage", 1)
        last = MATURITY_LAST_STAGE.get(meta.get("maturity"), 7)
        questions = canon.questions()
        blocking = [q for q in questions if q.get("blocking")]
        source = contract if isinstance(contract, dict) and contract.get("requirements") else spec
        reqs = source.get("requirements") if isinstance(source, dict) else None
        reqs = [r for r in reqs or [] if isinstance(r, dict) and r.get("provenance") != "withdrawn"]
        validations = canon.cards(state=None, kind="validation")
        counts = {
            1: _count("blocking open", sum(q["status"] == "open" for q in blocking), len(blocking)),
            2: _count("questions open", sum(q["status"] == "open" for q in questions), len(questions)),
            3: _count("requirements", len(reqs)),
            4: _count("criteria", sum(len(r.get("acceptance") or []) for r in reqs)),
            5: _count("tasks merged", sum(t["status"] == "merged" for t in tasks), len(tasks)),
            6: _count("validations open", sum(c["state"] == "open" for c in validations), len(validations)),
            7: _count("releases", len(releases)),
        }
        band_of = {n: band for band, _, stages in BANDS for n in stages}
        stages = []
        for n, name in STAGES.items():
            state = "done" if n < stage else "now" if n == stage else "off" if n > last else "ahead"
            row = {"stage": n, "name": name, "band": band_of[n], "state": state, "count": counts[n]}
            if n == 5 and evidence_counts is not None:
                # Build and verify: what a gate proved, apart from what a test only claims (FR-O6).
                row["evidence"] = {k: evidence_counts.get(k, 0) for k in ("verified", "claimed")}
            stages.append(row)
        return {"current": stage, "last": last, "stages": stages,
                "bands": [{"id": band, "label": label, "stages": list(ns)} for band, label, ns in BANDS]}

    @staticmethod
    def _status(fn, project, problems: list | None = None):
        """One of kernel.status's read models. A record it cannot read (a file of an unexpected
        shape) is reported in the view's problems and shown as not known, never a crash of the
        whole view; its own route still answers 500 with the error's name."""
        try:
            return fn(project)
        except Exception as exc:  # noqa: BLE001 - reported, not hidden: the page shows "unreadable"
            if problems is not None:
                problems.append(f"{fn.__name__}: {type(exc).__name__}")
            return None

    @staticmethod
    def _evidence_summary(rows) -> dict:
        """Counts per evidence state, for the project and for each requirement (FR-O6)."""
        counts = {s: 0 for s in EVIDENCE_STATES}
        by_req: dict = {}
        for row in rows or []:
            state = row.get("state", "not_measured")
            counts[state] = counts.get(state, 0) + 1
            req = by_req.setdefault(row.get("requirement"), {s: 0 for s in EVIDENCE_STATES})
            req[state] = req.get(state, 0) + 1
        return {"counts": counts, "total": sum(counts.values()), "by_requirement": by_req}

    # reads

    def get_meta(self, **_):
        return 200, {
            "origin": self.server.origin,
            # the access mode for the header; with access enforced, who is signed in and their grants
            "access": kaccess.view(self.access, self.identity),
            "stages": {str(n): name for n, name in STAGES.items()},
            "modes": {m: MODE_MEANING.get(m, "") for m in MODES},
            "maturities": {m: MATURITY_MEANING.get(m, "") for m in MATURITIES},
            "perspectives": list(PERSPECTIVES),
            "classes": {c: {"way_back": WAY_BACK[c], "stage": STAGES[WAY_BACK[c]],
                            "needs_decision": c in NEEDS_DECISION} for c in CLASSES},
            "card_kinds": {k: {"verdicts": list(v), "deciders": list(CARD_DECIDERS[k])}
                           for k, v in CARD_VERDICTS.items()},
            "bands": [{"id": band, "label": label, "stages": list(ns)} for band, label, ns in BANDS],
            "maturity_last_stage": dict(MATURITY_LAST_STAGE),
            "factory": {"id": FACTORY_PID, "title": FACTORY_TITLE},
            "may_pause": list(MAY_PAUSE),
            "plan_editors": list(CARD_DECIDERS["approval"]),
            "criterion_kinds": list(CRITERION_KINDS),
            # the redesigned cockpit: lenses, the widget library and its presets, the theme's fixed sets
            "lenses": {k: {"label": v["label"], "icon": v["icon"], "question": v["question"]} for k, v in LENSES.items()},
            "persona_lens": {p: lens_for(p) for p in PERSONAS},
            "widgets": {k: {"title": t, "icon": i, "question": q} for k, (t, i, q) in WIDGETS.items()},
            "lens_defaults": {k: [{"type": t, "size": s} for t, s in v] for k, v in LENS_DEFAULTS.items()},
            "layout": {"sizes": list(kassistant.SIZES), "views": list(LAYOUT_VIEWS), "max_widgets": MAX_WIDGETS,
                       "theme": {k: list(v) for k, v in kassistant.THEME.items()},
                       "font_scale": list(kassistant.FONT_SCALE)},
            "profiles": kprofiles.public(),
            "deliverables": dict(kprofiles.DELIVERABLES),
            "catalogue_states": list(kdash.CATALOGUE_STATES),
            "signal_channels": list(ksignals.CHANNELS),
            "concept_editors": list(CARD_DECIDERS["concept"]),
            "embed_kinds": list(kembeds.KINDS),
            "embed_creators": list(kembeds.CREATORS),
            **self._embed_base_view(),
            "pack_builders": list(PACK_BUILDERS),
            "comment_targets": list(Canon.COMMENT_TARGETS),
            "comment_promoters": list(PROMOTERS),
            "evidence_exporters": list(kevidence.EXPORTERS),
            "autonomy": {"levels": {str(n): {"name": kautonomy.LEVELS[n], "meaning": kautonomy.MEANING[n]}
                                    for n in kautonomy.LEVELS}, "setters": list(kautonomy.SETTERS)},
            "postures": kposture.public(),       # the postures and their weights (kernel/posture.py)
            "update_triggers": {k: v["label"] for k, v in TRIGGERS.items()},
            # autopilot, delegation and tracking (kernel/autopilot.py, kernel/delegation.py, kernel/track.py)
            "autopilot": {"may_run": list(kautopilot.MAY_RUN), "rules": kdelegation.RULES,
                          "never": kdelegation.NEVER, "max_days": kdelegation.MAX_DAYS,
                          "track_setters": list(ktrack.SETTERS), "checkpoint_lookers": list(ktrack.LOOKERS)},
            # who changes a project's settings or sends it back a step, and who adds material (FR-CHG1)
            "change": {"changers": list(krewind.CHANGERS), "material_adders": list(kadded.ADDERS),
                       "steps": [{"id": s, "undoes": krewind.UNDOES[s]} for s in krewind.STEPS]},
            "chat_model": self.server.shape_model is not None,
            "assistant": "map" if self.server.assistant_model is None
            else "gnomon" if type(self.server.assistant_model).__name__ == "GnomonModel" else "model",
        }

    def get_personas(self, **_):
        out = []
        for p in PERSONAS:
            label, sees, can = PERSONA_INFO.get(p, (p.replace("_", " ").capitalize(), "", ""))
            out.append({"id": p, "label": label, "sees": sees, "can": can, "lens": lens_for(p),
                        "decides": [k for k, who in CARD_DECIDERS.items() if p in who]})
        return 200, out

    def get_projects(self, **_):
        out = []
        for project in self.factory.projects():
            meta = project.meta
            canon = Canon(project)
            by_kind: dict = {}
            for card in canon.cards(state="open"):
                by_kind[card["kind"]] = by_kind.get(card["kind"], 0) + 1
            stage = meta.get("stage", 1)
            out.append({"id": project.pid, "title": _factory_label(project.pid, meta.get("title", project.pid)),
                        "factory": project.pid == FACTORY_PID,
                        "maturity": meta.get("maturity"), "mode": meta.get("mode"), "stage": stage,
                        "stage_name": STAGES.get(stage, "?"), "open_cards": sum(by_kind.values()),
                        "open_by_kind": by_kind, "stale_approvals": len(canon.decisions(stale=True)),
                        "overdue_assumptions": len(canon.overdue()), "updated": meta.get("updated"),
                        "profile": meta.get("profile") or kprofiles.DEFAULT_PROFILE,
                        "paused": bool(meta.get("pause")), "now": self._status(now, project),
                        "running": self._running(project),
                        "last_cell": None if project.pid == FACTORY_PID else self._last_cell(project)})
        out.sort(key=lambda row: not row["factory"])  # Rihma's own proposals first; the rest keep their order
        return 200, out

    def get_project(self, pid: str, **_):
        project = self._project(pid)
        canon = Canon(project)
        meta = dict(project.meta)
        meta["stage_name"] = STAGES.get(meta.get("stage"), "?")
        meta["title"] = _factory_label(pid, meta.get("title", pid))
        meta["factory"] = pid == FACTORY_PID
        problems: list = []
        if not meta.get("requested_by"):
            # A project a validated concept made keeps who asked for it in its need, not in project.json.
            need = self._read(project, "need.json", None, problems)
            if isinstance(need, dict) and need.get("requested_by"):
                meta["requested_by"] = need["requested_by"]
        overdue = {a["id"] for a in canon.overdue()}
        assumptions = [dict(a, overdue=a["id"] in overdue) for a in canon.assumptions()]
        decisions = canon.decisions()
        open_cards = [{k: self._card_title(c) if k == "title" else c.get(k)
                       for k in ("id", "kind", "title", "blocking", "created", "refs")}
                      for c in canon.cards(state="open")]
        changes = [self._card_view(c, canon) for c in canon.cards(state=None, kind="change")]
        contract = self._read(project, "contract.json", None, problems)
        spec = self._read(project, "spec.json", None, problems)
        tasks = self._tasks(contract, self._read(project, "tasks.json", {}, problems))
        releases = self._releases(project, problems)
        criteria = self._status(evidence, project, problems)
        summary = self._evidence_summary(criteria)
        return 200, {
            "meta": meta,
            "now": self._status(now, project, problems),
            "health": self._status(health, project, problems),
            "evidence": criteria or [],
            "evidence_summary": summary,
            "stage_summary": self._stage_summary(meta, canon, spec, contract, tasks, releases, summary["counts"]),
            "goal": canon.goal,
            "brief": canon.brief,
            "readings": self._read(project, "readings.json", {}, problems),
            # what the input stated, what was asked, what was assumed (docs/guides/inputs.md)
            "intake_summary": kinputs.summary(project, self._read(project, "inputs.json", None, problems) or {}),
            "questions": [self._question_view(q, canon) for q in canon.questions()],
            "assumptions": assumptions,
            "decisions": decisions,
            "stale": [d for d in decisions if d.get("stale")],
            "open_cards": open_cards,
            "changes": changes,
            "spec": spec,
            "contract": self._contract_summary(contract, spec),
            "tasks": tasks,
            "releases": releases,
            "lessons": self._read(project, "lessons.json", [], problems),
            "ledger": self.server.check_ledger(project),
            "jobs": [self.server.job_view(j) for j in list(self.server.jobs) if j["project"] == pid][::-1],
            "profile": kprofiles.public(meta.get("profile") or kprofiles.DEFAULT_PROFILE)
            if (meta.get("profile") or kprofiles.DEFAULT_PROFILE) in kprofiles.PROFILES else None,
            "autonomy": None if pid == FACTORY_PID else self._autonomy_of(project),
            "track": None if pid == FACTORY_PID else self._status(ktrack.summary, project, problems),
            "running": self._running(project),
            "last_cell": None if pid == FACTORY_PID else self._last_cell(project),
            **self._next_and_change(project, problems),     # what it waits for, what may change (FR-CHG1)
            "problems": problems,
        }

    def _next_and_change(self, project: Project, problems: list) -> dict:
        """``next`` (kernel/next_step.py) and ``change`` (the settings, steps and material) of a project; None
        for Rihma's own canon, which has neither."""
        if project.pid == FACTORY_PID:
            return {"next": None, "change": None}
        return {"next": self._status(self._next_of, project, problems),
                "change": self._status(self._change_view, project, problems)}

    @staticmethod
    def _change_view(project: Project) -> dict:
        """The settings as they stand, each step a person may go back to and what it would set aside, and the
        material added so far (its notes, not its text)."""
        added = kadded.material(project)["added"]
        return {"settings": ksettings.current(project),
                "steps": [{k: v for k, v in krewind.preview(project, s).items() if k != "steps"}
                          for s in krewind.STEPS],
                "material": [{k: a.get(k) for k in ("n", "note", "chars", "by", "at", "path")} for a in added],
                "superseded": krewind.superseded(project)}

    @staticmethod
    def _contract_summary(contract, spec=None) -> dict | None:
        if not isinstance(contract, dict):
            return None
        # The contract keeps no sources; the spec it was compiled from does (kernel/spec.py).
        spec_reqs = spec.get("requirements") if isinstance(spec, dict) else None
        sources = {r.get("id"): r.get("sources") or [] for r in spec_reqs or [] if isinstance(r, dict)}
        reqs = []
        for r in contract.get("requirements", []):
            reqs.append({
                "id": r.get("id"), "statement": r.get("statement"), "provenance": r.get("provenance"),
                "group": r.get("group"), "decided_by": r.get("decided_by"), "decided_on": r.get("decided_on"),
                "sources": sources.get(r.get("id")) or (["factory default"] if r.get("group") == "factory-default"
                                                        else []),
                "criteria": [{"id": c.get("id"), "kind": (c.get("check") or {}).get("kind"),
                              "provenance": r.get("provenance"), "given": c.get("given"), "when": c.get("when"),
                              "then": c.get("then")} for c in r.get("acceptance", [])],
            })
        return {"revision": contract.get("revision"), "counts": contract.get("counts"), "requirements": reqs,
                "tasks": [{"id": t.get("id"), "title": t.get("title"), "criteria": t.get("criteria", []),
                           "depends_on": t.get("depends_on", [])} for t in contract.get("tasks", [])]}

    @staticmethod
    def _tasks(contract, state) -> list:
        state = state if isinstance(state, dict) else {}
        planned = contract.get("tasks", []) if isinstance(contract, dict) else []
        order = [t.get("id") for t in planned] + sorted(t for t in state if t not in {p.get("id") for p in planned})
        titles = {t.get("id"): t for t in planned}
        out = []
        for tid in order:
            s = state.get(tid) or {}
            plan = titles.get(tid) or {}
            rounds = []
            for r in s.get("rounds") or []:
                gate = r.get("gate") or None
                rounds.append({"round": r.get("round"), "cell": r.get("cell") or {},
                               "gate": None if gate is None else {
                                   "verdict": gate.get("verdict"), "warranted": gate.get("warranted"),
                                   "head": gate.get("head"), "objections": gate.get("objections") or [],
                                   "signals": [{"name": sig.get("name"), "verdict": sig.get("verdict"),
                                                "detail": sig.get("detail")} for sig in gate.get("signals") or []]}})
            out.append({"id": tid, "title": plan.get("title"), "criteria": plan.get("criteria", []),
                        "depends_on": plan.get("depends_on", []), "status": s.get("status", "pending"),
                        "revision": s.get("revision"), "card": s.get("card"), "permitted_by": s.get("permitted_by"),
                        "reopened_by": s.get("reopened_by"), "stopped_by": s.get("stopped_by"),
                        "accepted_as_is_by": s.get("accepted_as_is_by"), "rounds": rounds})
        return out

    def _releases(self, project, problems: list) -> list:
        folder = project.path("releases")
        if not folder.is_dir():
            return []
        out = []
        for path in sorted(folder.glob("*.json"), key=_natural):
            data = self._read(project, f"releases/{path.name}", None, problems)
            out.append({"name": path.stem, "data": data})
        return out

    def get_inbox(self, pid: str, query: dict, **_):
        project = self._project(pid)
        persona = query.get("persona", "")
        if persona not in PERSONAS:
            raise ApiError(400, f"persona must be one of {', '.join(PERSONAS)}")
        canon = Canon(project)
        cards = [self._card_view(c, canon) for c in canon.cards(state="open", persona=persona)]
        return 200, {"persona": persona, "cards": cards}

    def get_impact(self, pid: str, query: dict, **_):
        """Impact if changed, for any requirements: ``?requirements=R-1,R-2`` (FR-P5)."""
        project = self._project(pid)
        rids = [r.strip() for r in query.get("requirements", "").split(",") if r.strip()]
        if not rids:
            raise ApiError(400, "name the requirements: ?requirements=R-1,R-2")
        if len(rids) > 200 or not all(_REQ_ID.match(r) for r in rids):
            raise ApiError(400, "requirements must be requirement ids such as R-1, separated by commas")
        return 200, impact(project, rids)

    def get_alignment(self, pid: str, **_):
        """The canon's contradictions, listed rather than resolved silently (FR-S6)."""
        return 200, alignment(self._project(pid))

    def get_cell(self, pid: str, **_):
        """Every Gnomon run of the project (FR-M3)."""
        return 200, cell(self._project(pid))

    def get_evidence(self, pid: str, **_):
        """Each criterion's evidence state: verified, claimed, held out, failing or not measured (FR-O6)."""
        return 200, evidence(self._project(pid))

    def get_now(self, pid: str, **_):
        """One line on what the project is doing, with its state (FR-T1)."""
        return 200, now(self._project(pid))

    def get_health(self, pid: str, **_):
        """On track, at risk or off track, the reasons, and a forecast from the project's own history (FR-T1)."""
        return 200, health(self._project(pid))

    # the plan before building (FR-P7), the running cell (FR-T1) and what to try (FR-R1)

    @staticmethod
    def _plan_cards(canon: Canon, state: str | None) -> list:
        return [c for c in canon.cards(state=state, kind="approval") if (c.get("refs") or {}).get("scope") == "plan"]

    @staticmethod
    def _plan_spec(spec, version: int) -> dict | None:
        """The plan as people read it: each requirement with its criteria, provenance and owner."""
        if not isinstance(spec, dict):
            return None
        reqs = []
        for r in spec.get("requirements") or []:
            if not isinstance(r, dict):
                continue
            reqs.append({"id": r.get("id"), "statement": r.get("statement"), "provenance": r.get("provenance"),
                         "decided_by": r.get("decided_by"), "priority": r.get("priority"),
                         "sources": r.get("sources") or [],
                         "acceptance": [{k: c.get(k) for k in ("id", "given", "when", "then", "kind")}
                                        for c in r.get("acceptance") or [] if isinstance(c, dict)]})
        return {"title": spec.get("title"), "summary": spec.get("summary"), "version": version,
                "requirements": reqs, "interface": spec.get("interface") or [],
                "out_of_scope": spec.get("out_of_scope") or [], "integrations": spec.get("integrations") or []}

    def _plan_view(self, project) -> dict:
        canon = Canon(project)
        problems: list = []
        version = int(project.meta.get("spec_version", 1))
        spec = self._read(project, "spec.json", None, problems)
        opened = self._plan_cards(canon, "open")
        card = next((c for c in opened if c["refs"].get("spec_version") == version), opened[0] if opened else None)
        history = []
        for c in self._plan_cards(canon, None):
            if c["state"] == "open":
                continue
            d = c.get("decision") or {}
            history.append({"card": c["id"], "state": c["state"], "spec_version": c["refs"].get("spec_version"),
                            "verdict": d.get("verdict"), "person": d.get("person"), "persona": d.get("persona"),
                            "reason": d.get("reason"), "at": d.get("at"), "redone": bool(c["refs"].get("redone")),
                            "closed": c.get("closed")})
        from kernel.posture_rules import confirmers   # a confirming posture: the customer's side edits the plan

        editors = confirmers(kposture.of(project)) or CARD_DECIDERS["approval"]
        return {"required": kplan.required(project), "card": self._card_view(card, canon) if card else None,
                "approved": project.meta.get("plan_approved"), "compiled": project.path("contract.json").exists(),
                "editors": list(editors), "spec": self._plan_spec(spec, version),
                "history": history, "problems": problems}

    def get_plan(self, pid: str, **_):
        """The plan that waits on a person before anything is built (FR-P7): whether this project needs
        the approval, its open card, who approved it, and the spec's requirements with their criteria.
        Reading it opens no card: the pipeline does that."""
        return 200, self._plan_view(self._project(pid))

    def get_live(self, pid: str, **_):
        """What the project's running Gnomon cell is doing, read from Gnomon's own audit trail in the lane
        it holds (``$GF_LANES``, else ``~/gf-lanes``); "not running" when no lane is held (FR-T1)."""
        return 200, live(self._project(pid))

    def get_try(self, pid: str, **_):
        """The release to try and one plain check per criterion, with its evidence state (FR-R1)."""
        return 200, try_it(self._project(pid))

    def get_floor(self, **_):
        """The factory's runs by phase and verdict, its spend, and each builder model's record (FR-M3, FR-F8)."""
        out = floor(self.factory)
        out["currency"] = load_prices().get("currency", "USD")
        out["model_reliability"] = model_reliability(self.factory)
        out["immune_memory"] = immune_memory(self.factory)
        return 200, out

    def get_jobs(self, query: dict, **_):
        pid = query.get("project")
        jobs = [j for j in list(self.server.jobs) if not pid or j["project"] == pid]
        return 200, [self.server.job_view(j) for j in jobs][::-1]

    # writes: each one signed by a person and a persona; the kernel decides whether it stands

    def post_decide(self, pid: str, cid: str, body: dict, **_):
        project = self._project(pid)
        canon = Canon(project)
        verdict = _text(body, "verdict", required=True, limit=64)
        reason = _text(body, "reason")
        person, persona = self._who(body, pid)
        try:
            card = canon.get_card(cid)
        except KeyError:
            raise ApiError(404, f"no card {cid}") from None
        qid = (card.get("refs") or {}).get("question")
        if card["kind"] == "question" and qid and card["state"] == "open":
            # A question card is settled through the question, so the canon's question moves too.
            if verdict == "answer":
                return self._answer(project, qid, reason, person, persona)
            if verdict == "assume":
                return self._assume(project, qid, person, persona)
        if card["kind"] == "concept" and verdict in ("park", "reject") and not reason.strip():
            # A need is parked or rejected with the reason why, for whoever raised it; nothing is recorded
            # without one.
            raise ApiError(400, f"Say why you {verdict} {cid}: a concept is parked or rejected with the reason, "
                                f"recorded with the decision. Write it on the concept's card on the Square.")
        decision = canon.decide(cid, verdict, person=person, persona=persona, reason=reason)
        self._audit(project, "decide", cid, person, persona, verdict=verdict)
        out = {"decision": decision, "card": self._card_view(canon.get_card(cid), canon)}
        # A decided concept (the factory's canon) or update card is carried out at once, as the kernel's
        # loops would: a validated concept becomes a project, a trial is recorded for the operator.
        if card["kind"] == "concept":
            out["applied"] = ksignals.apply_concepts(self.factory)
            made = next((a for a in out["applied"] if a.get("card") == cid and a.get("project")), None)
            if made is not None:
                out["project"] = made["project"]     # the page opens the new project at once
        elif card["kind"] == "update":
            out["applied"] = apply_updates(project)
        return 200, out

    def post_answer(self, pid: str, qid: str, body: dict, **_):
        project = self._project(pid)
        text = _text(body, "text", required=True)
        person, persona = self._who(body, pid)
        return self._answer(project, qid, text, person, persona)

    def _answer(self, project, qid: str, text: str, person: str, persona: str):
        if not text:
            raise ApiError(400, "an answer needs text")
        canon = Canon(project)
        try:
            options = self._options(canon.question(qid))
            q = canon.answer(qid, text, person=person, persona=persona)
        except KeyError:
            raise ApiError(404, f"no question {qid}") from None
        # An answer that is one of the options keeps which one it was (0 is the panel's proposal).
        chosen = {"option": options.index(text)} if text in options else {}
        self._audit(project, "answer", qid, person, persona, **chosen)
        brief = render_brief(project)
        return 200, {"question": self._question_view(q, canon), "brief": brief}

    def post_assume(self, pid: str, qid: str, body: dict, **_):
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return self._assume(project, qid, person, persona)

    def _assume(self, project, qid: str, person: str, persona: str):
        """"Let the factory assume": the asking perspective's proposed answer becomes an assumption
        with a due date, and the person who chose it is recorded on the question's card."""
        canon = Canon(project)
        try:
            q = canon.question(qid)
        except KeyError:
            raise ApiError(404, f"no question {qid}") from None
        if q["status"] != "open":
            raise ApiError(403, f"refused: {qid} is {q['status']}, not open")
        _require_person(person, persona)
        proposed = str((q.get("opinions") or {}).get(q["perspective"]) or "").strip()
        if not proposed:
            raise ApiError(409, f"the {q['perspective']} perspective proposed no answer to {qid}: answer it instead")
        if not q.get("card"):
            canon.ask(qid)  # put it to a person first, so the choice is a signed decision on its card
        assumption = canon.assume(qid, proposed, chosen_by=person, persona=persona)
        self._audit(project, "assume", qid, person, persona, assumption=assumption["id"])
        brief = render_brief(project)
        return 200, {"assumption": assumption, "question": self._question_view(canon.question(qid), canon),
                     "brief": brief}

    def post_settle(self, pid: str, aid: str, body: dict, **_):
        project = self._project(pid)
        confirmed = body.get("confirmed")
        if not isinstance(confirmed, bool):
            raise ApiError(400, "confirmed must be true or false")
        correction = _text(body, "correction")
        if not confirmed and not correction:
            raise ApiError(400, "a refuted assumption needs the correction")
        person, persona = self._who(body, pid)
        canon = Canon(project)
        try:
            a = canon.settle_assumption(aid, confirmed=confirmed, person=person, persona=persona,
                                        correction=correction)
        except KeyError:
            raise ApiError(404, f"no assumption {aid}") from None
        self._audit(project, "settle", aid, person, persona, confirmed=confirmed)
        render_brief(project)
        return 200, {"assumption": a}

    def post_change(self, pid: str, body: dict, **_):
        project = self._project(pid)
        person, persona = self._who(body, pid)
        _require_person(person, persona)
        text = _text(body, "text", required=True)
        hint = _text(body, "hint", limit=64) or None
        if hint is not None and hint not in CLASSES:
            raise ApiError(400, f"hint must be one of {', '.join(CLASSES)}")
        try:
            card = submit(project, persona=persona, person=person, text=text, kind_hint=hint)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        result = triage(project, card["id"], model=None)
        canon = Canon(project)
        return 201, {"card": self._card_view(canon.get_card(card["id"]), canon), "triage": result}

    @staticmethod
    def _how_it_runs(body: dict) -> tuple[str | None, str | None, str | None]:
        """The posture, mode and maturity a new project is asked with: with a posture, its own mode and
        maturity unless named (the kernel checks them against it); without one, mixed and demo unless named."""
        posture = _text(body, "posture", limit=32) or None
        mode = _text(body, "mode", limit=32) or (None if posture else "mixed")
        maturity = _text(body, "maturity", limit=32) or (None if posture else "demo")
        if mode is not None and mode not in MODES:
            raise ApiError(400, f"mode must be one of {', '.join(MODES)}")
        if maturity is not None and maturity not in MATURITIES:
            raise ApiError(400, f"maturity must be one of {', '.join(MATURITIES)}")
        return posture, mode, maturity

    def post_project(self, body: dict, **_):
        title = _text(body, "title", required=True, limit=200)
        source = _text(body, "source", required=True, limit=200_000)
        posture, mode, maturity = self._how_it_runs(body)
        requested_by = _text(body, "requested_by", limit=200)
        persona = _text(body, "persona", limit=64) or "business_owner"
        profile = _text(body, "profile", limit=64) or None
        if profile is not None and profile not in kprofiles.PROFILES:
            raise ApiError(400, f"profile must be one of {', '.join(kprofiles.PROFILES)}")
        requested_by, persona = self._sign(requested_by, persona, FACTORY_PID)
        _require_person(requested_by, persona)
        kisolation.require(self.factory)     # the intake job asks Gnomon cells: never unisolated while enforced
        outputs = self._intake_outputs(body, persona)
        source, scanned, secret = self._folder_request(body, source, persona)
        chosen = {"name": posture, "weights": _weights_in(body), "by": requested_by, "persona": persona} \
            if posture else None
        try:
            project = self.factory.new_project(title, maturity=maturity, mode=mode, profile=profile, posture=chosen)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        if secret:
            kconfidential.mark(project, person=requested_by, persona=persona)
        from kernel.go_ahead import choose as wait_or_not  # a look at the spec before the first build, unless told not

        wait_or_not(project, wait=body.get("build_without_waiting") is not True, person=requested_by, persona=persona,
                    where="New project")
        if scanned is not None:     # the map the person saw in the scan step, kept with who confirmed it
            kmaterial.record(project, scanned, person=requested_by, persona=persona,
                             confirmed="in the cockpit's scan step")
        if outputs:
            koutputs.choose(project, outputs, person=requested_by, persona=persona, when="intake")
        # With access enforced the record carries the request's digest: the intake job, which runs as the
        # cockpit's own account, carries out this signed request and no other (kernel.access.cli_signing).
        signed = {"request_sha256": kaccess.request_digest(source)} if self.access.enforced else {}
        if posture:
            signed["posture"] = posture
        self._audit(project, "new_project", project.pid, requested_by, persona, **signed)
        source_file = self.server.jobs_dir / f"{project.pid}.source.md"
        write_text(source_file, source if source.endswith("\n") else source + "\n")
        job = self.server.start_job("intake", project.pid,
                                    ["-m", "kernel.cli", "intake", project.pid, "--source-file", str(source_file),
                                     "--requested-by", requested_by],
                                    {"person": requested_by, "persona": persona})
        return 201, {"project": project.meta, "job": self.server.job_view(job)}

    @staticmethod
    def _excludes(body: dict) -> list[str]:
        """The files a person unticked in the scan step, or patterns: a list of short texts."""
        raw = body.get("exclude") or []
        if not isinstance(raw, list) or len(raw) > 5000 or not all(isinstance(x, str) and 0 < len(x) <= 1000
                                                                   and "\n" not in x for x in raw):
            raise ApiError(400, "exclude must be a list of at most 5000 paths or patterns")
        return [x.strip() for x in raw if x.strip()]

    def _folder_request(self, body: dict, source: str, persona: str) -> tuple[str, dict | None, bool]:
        """A new project's request: its own text, or a folder the person scanned and confirmed (the request is
        built from its material map, without the files they unticked). Confidential is refused here, before
        anything is created, while the analyst's endpoint is hosted."""
        secret = body.get("confidential") is True
        if secret and (why := kconfidential.refusal(["analyst"])):
            raise ApiError(403, why)
        if body.get("folder") is not True:
            return source, None, secret
        path = ksource.check_folder(source, persona)
        mp, text, _ = kmaterial.gather(path, self._excludes(body))
        if not text.strip():
            raise ApiError(400, "the scan of that folder found nothing to read: every file is listed or skipped")
        return text, mp, secret

    def post_source_preview(self, body: dict, **_: object) -> tuple[int, dict]:
        """The material map of a local folder, before anything is sent or created: what would be read,
        summarised, listed and skipped, and why (kernel/material.py). Only a persona that may create or adopt
        a project, signed, and only a folder under the user's home or the configured roots (kernel/source_guard.py).
        It reads files and records nothing."""
        person, persona = self._sign(_text(body, "person", limit=200), _text(body, "persona", limit=64), FACTORY_PID)
        _require_person(person, persona)
        path = ksource.check_folder(_text(body, "source", required=True, limit=2000), persona)
        mp = kmaterial.preview(path, self._excludes(body))
        from kernel.material_adopt import is_git

        return 200, {"map": mp, "git": is_git(path), "code": kmaterial.has_code(mp),
                     "send_to": kconfidential.send_to("analyst"),
                     "local_only": {"new": kconfidential.refusal(["analyst"]) or None,
                                    "all": kconfidential.refusal(kconfidential.ROLES) or None}}

    def _adopt_how(self, body: dict) -> tuple[str | None, str, list[str]]:
        """How an adopted project runs: a posture with its weights, maturity and mode (refused here, before
        anything is read, by the posture's rules), or none, at production and mixed as before. Returns the
        posture, the maturity and the command line's words for them."""
        posture, mode, maturity = self._how_it_runs(body)
        maturity = maturity if posture or _text(body, "maturity", limit=32) else "production"
        weights = _weights_in(body)
        if posture:
            eff = kposture.effects(posture, weights, maturity=maturity, mode=mode)
            maturity, mode = eff["maturity"], eff["mode"]
        given = ["--weights", ",".join(f"{k}={v}" for k, v in weights.items())] if posture and weights else []
        return posture, str(maturity), ["--maturity", str(maturity), "--mode", str(mode),
                                        *(["--posture", posture] if posture else []), *given]

    def post_adopt(self, body: dict, **_):
        """Adopt an existing project from a local folder (a git repository, or any folder with code, which is
        snapshotted) or an address git clones without credentials. It runs as a job: adopting reads the
        repository and runs its own test suites for a baseline."""
        from kernel.adopt import INTENTS, AdoptionRefused, check_source
        from kernel.material_adopt import NoCode, check_code

        title = _text(body, "title", required=True, limit=200)
        source = _text(body, "source", required=True, limit=2000).strip()
        intent = _text(body, "intent", limit=16) or "improve"
        posture, maturity, how = self._adopt_how(body)
        base_url = _text(body, "base_url", limit=500).strip() or None
        if intent not in INTENTS:
            raise ApiError(400, f"intent must be one of {', '.join(INTENTS)}")
        person, persona = self._sign(_text(body, "person", limit=200), _text(body, "persona", limit=64), FACTORY_PID)
        _require_person(person, persona)
        exclude = self._excludes(body)
        try:
            kind, location = check_source(source)
            if kind != "url":          # a local folder: read only where the cockpit may read for this person
                ksource.check_folder(location, persona)
            if kind == "folder":
                check_code(location, exclude)
        except (AdoptionRefused, NoCode, OSError) as exc:
            raise ApiError(400, str(exc)) from None
        kisolation.require(self.factory, kisolation.SUITE)   # its baseline runs the repository's own tests
        # The request is on record, signed, before the job runs (D-0017: no path skips the record).
        self._audit(self._factory_canon(), "adopt_requested", title, person, persona, source_kind=kind, intent=intent,
                    maturity=maturity, **({"posture": posture} if posture else {}))
        args = ["-m", "kernel.cli", "adopt", title, "--source", source, "--intent", intent, "--person", person,
                "--persona", persona, *how,
                *(["--base-url", base_url] if base_url else []),
                *(f"--exclude={x}" for x in exclude), *(["--confidential"] if body.get("confidential") is True else [])]
        job = self.server.start_job("adopt", FACTORY_PID, args, {"person": person, "persona": persona})
        return 201, {"job": self.server.job_view(job)}

    def post_advance(self, pid: str, body: dict, **_):
        project = self._project(pid)
        person, persona = self._who(body, pid)
        kisolation.require(self.factory)     # a run starts Gnomon cells and the gate's tests: isolated, or refused
        running = self.server.running_job(pid)
        if running is not None:
            raise ApiError(409, f"job {running['id']} is still running for {pid}")
        job = self.server.start_job("run", project.pid, ["-m", "kernel.cli", "run", project.pid],
                                    {"person": person or None, "persona": persona or None})
        return 202, {"job": self.server.job_view(job)}

    @staticmethod
    def _criteria_in(raw) -> list:
        """Criteria as a person typed them: given, when, then and the kind of check."""
        if not isinstance(raw, list) or len(raw) > MAX_CRITERIA:
            raise ApiError(400, f"acceptance must be a list of at most {MAX_CRITERIA} criteria")
        out = []
        for ac in raw:
            if not isinstance(ac, dict):
                raise ApiError(400, "each criterion must be an object with given, when, then and kind")
            row = {}
            for key in ("given", "when", "then"):
                row[key] = _text(ac, key, limit=2000)
            kind = ac.get("kind") or "test"
            if kind not in CRITERION_KINDS:
                raise ApiError(400, f"a criterion's kind must be one of {', '.join(CRITERION_KINDS)}")
            row["kind"] = kind
            out.append(row)
        if not any(row["then"] for row in out):
            raise ApiError(400, "a requirement needs at least one criterion with a 'then'")
        return out

    def post_plan_requirement(self, pid: str, rid: str, body: dict, **_):
        """A person changes a requirement before the plan is approved (FR-P7). The kernel refuses a
        non-person, a persona that may not edit the plan, and a plan already compiled. The edit makes
        the person the requirement's owner, and the plan's approval card is reissued for the edit."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        statement = _text(body, "statement", limit=4000) or None
        acceptance = None if body.get("acceptance") is None else self._criteria_in(body.get("acceptance"))
        if statement is None and acceptance is None:
            raise ApiError(400, "send the new statement, the criteria, or both")
        if not project.path("spec.json").exists():
            raise ApiError(409, f"{pid} has no plan yet: its spec is not written")
        try:
            req = kplan.edit_requirement(project, rid, person=person, persona=persona, statement=statement,
                                         acceptance=acceptance)
        except DecisionRefused:
            raise
        except KeyError:
            raise ApiError(404, f"no requirement {rid} in the plan") from None
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        self._audit(project, "edit_requirement", rid, person, persona)
        if kplan.required(project):
            kplan.open_card(project)  # the kernel reissues the card for the edited plan, as the pipeline would
        return 200, {"requirement": req, "plan": self._plan_view(project)}

    def post_pause(self, pid: str, body: dict, **_):
        """Ask the project to stop at its next safe point (FR-J3), signed with person and persona."""
        project = self._project(pid)
        if pid == FACTORY_PID:
            raise ApiError(400, "Rihma itself has no pipeline to pause")
        person, persona = self._who(body, pid)
        reason = _text(body, "reason", limit=2000)
        held = project.meta.get("pause")
        if held:
            raise ApiError(409, f"{pid} is already paused by {held.get('requested_by')}")
        state = request_pause(project, person=person, persona=persona, reason=reason)
        self._audit(project, "pause", pid, person, persona)
        return 200, {"pause": state, "now": now(project)}

    def post_resume(self, pid: str, body: dict, **_):
        """Lift a pause (FR-J3), signed with person and persona; the next Advance carries on."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        if not project.meta.get("pause"):
            raise ApiError(409, f"{pid} is not paused")
        resume(project, person=person, persona=persona)
        self._audit(project, "resume", pid, person, persona)
        return 200, {"now": now(project)}

    # -- change anything set for a project, go back a step, add material (FR-CHG1) -------------------------

    def _changing(self, pid: str, body: dict, *, idle: bool = True) -> tuple[Project, str, str]:
        """The project a change acts on and who signs it: never Rihma's own canon, nor while a job runs."""
        project = self._project(pid)
        if pid == FACTORY_PID:
            raise ApiError(400, "Rihma itself has no settings, steps or material to change")
        person, persona = self._who(body, pid)
        running = self.server.running_job(pid) if idle else None
        if running is not None:
            raise ApiError(409, f"job {running['id']} is still running for {pid}: change it once the job ends")
        return project, person, persona

    @staticmethod
    def _settings_in(body: dict) -> dict:
        flag = body.get("build_without_waiting")    # a yes or no (kernel/go_ahead.py); every other field is text
        return {f: (flag if isinstance(flag, bool) else None) if f == "build_without_waiting"
                else _text(body, f, limit=ksettings.MAX_TITLE) or None for f in ksettings.FIELDS}

    def _next_of(self, project: Project) -> dict:
        """What the project waits for (kernel/next_step.py), with its last run's result when a job ran."""
        pid = project.pid
        runs = [self.server.job_view(j) for j in list(self.server.jobs) if j["project"] == pid and j["kind"] == "run"]
        running = any(j["state"] == "running" for j in runs) or self.server.running_job(pid) is not None
        job = next((j for j in reversed(runs) if j.get("outcome")), None)
        return knext.next_step(project, last=job and job["outcome"], running=running,
                               last_started=job and job["started"])

    def put_settings(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """Change the title, kind of work, mode or maturity, signed with a reason; ``redo`` carries it into the work."""
        project, person, persona = self._changing(pid, body)
        out = ksettings.change(project, person=person, persona=persona, reason=_text(body, "reason", limit=2000),
                               redo=body.get("redo") is True, **self._settings_in(body))
        self._audit(project, "change_settings", pid, person, persona, fields=sorted(out["changed"]))
        return 200, {**out, "next": self._next_of(project)}

    def post_settings_preview(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """What a settings change would do: the impact on the work done. It writes nothing."""
        project, _, _ = self._changing(pid, body, idle=False)
        return 200, ksettings.preview(project, **self._settings_in(body))

    def post_rewind(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """Go back a step so it runs again; what it sets aside is kept as superseded, never deleted."""
        project, person, persona = self._changing(pid, body)
        to = _text(body, "to", required=True, limit=16)
        try:
            out = krewind.rewind(project, to=to, person=person, persona=persona, reason=_text(body, "reason",
                                                                                              limit=2000))
        except krewind.RewindRefused as exc:
            raise ApiError(409, f"refused: {exc}") from None
        self._audit(project, "rewind", pid, person, persona, to=to)
        return 200, {**out, "next": self._next_of(project)}

    def post_material(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """Add material to the request; with ``reintake`` a run starts and the panel reads the new material."""
        project, person, persona = self._changing(pid, body)
        path = _text(body, "path", limit=2000) or None
        if path and self.access.enforced:
            raise ApiError(403, "refused: with access enforced the cockpit reads no file on its own machine for a "
                                "request; paste the material as text")
        reintake = body.get("reintake") is True
        if reintake:                         # the run asks Gnomon cells: isolated while enforced, or refused
            kisolation.require(self.factory)
        try:
            out = kadded.add_material(project, person=person, persona=persona, path=path, reintake=reintake,
                                         text=_text(body, "text", limit=kadded.MAX_MATERIAL) or None,
                                         note=_text(body, "note", limit=300))
        except (FileNotFoundError, IsADirectoryError) as exc:
            raise ApiError(400, f"the material could not be read: {exc}") from None
        self._audit(project, "add_material", pid, person, persona, n=out["n"])
        job = None
        if reintake:   # the run reads it first (kernel/project_material.py pending_intake)
            job = self.server.job_view(self.server.start_job("run", project.pid, ["-m", "kernel.cli", "run", pid],
                                                             {"person": person, "persona": persona}))
        return 200, {**out, "job": job, "next": self._next_of(project)}

    # -- autopilot, delegation and staying on track (kernel/autopilot.py, kernel/track.py, D-0017) -------

    def get_track(self, pid: str, **_: object) -> tuple[int, dict]:
        """A project against its approved plan, with its checkpoints, autopilot and delegations. A read
        (Rihma's own canon has no plan: its track is not measured)."""
        project = self._project(pid)
        return 200, {"track": ktrack.track(project), "autopilot": kautopilot.status(project),
                     "settings": ktrack.settings(project)}

    def put_tracking(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """A plan owner sets the checkpoints, whether a due one holds the run, and the budget."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        stages, hold, amount = body.get("checkpoints"), body.get("hold"), body.get("budget")
        if stages is not None and not (isinstance(stages, list) and all(type(s) is int for s in stages)):
            raise ApiError(400, "checkpoints is a list of stage numbers")
        if hold is not None and not isinstance(hold, bool):
            raise ApiError(400, "hold is true or false")
        if amount is not None and type(amount) not in (int, float):
            raise ApiError(400, "budget is a number")
        out = ktrack.set_tracking(project, person=person, persona=persona, stages=stages, hold=hold,
                                  due=body["due"] if isinstance(body.get("due"), str) else None, amount=amount,
                                  currency=_text(body, "currency", limit=8) or None)
        self._audit(project, "tracking_set", pid, person, persona)
        return 200, {"settings": out, "track": ktrack.summary(project)}

    def post_checkpoint_look(self, pid: str, stage: str, body: dict, **_: object) -> tuple[int, dict]:
        """A person records that they looked at a checkpoint; a run it held goes on at its next pass."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        cps = ktrack.look(project, int(stage), person=person, persona=persona, note=_text(body, "note", limit=2000))
        self._audit(project, "checkpoint_look", stage, person, persona)
        return 200, {"checkpoints": cps, "track": ktrack.summary(project)}

    def post_autopilot_start(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """Arm an autopilot (its delegation in the signer's name, bound to the sandbox) and run its passes
        as a job. The kernel refuses a kind that is never delegated, or one the persona may not decide."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        kinds, rules = body.get("kinds"), body.get("rules") or {}
        if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
            raise ApiError(400, "kinds is a list of card kinds")
        if not isinstance(rules, dict) or not all(isinstance(v, str) for v in rules.values()):
            raise ApiError(400, "rules maps a card kind to its rule")
        running = self.server.running_job(pid)
        if running is not None:
            raise ApiError(409, f"job {running['id']} is still running for {pid}")
        kisolation.require(self.factory)     # its passes start Gnomon cells: isolated while enforced, or refused
        run = kautopilot.start(project, until=_text(body, "until", required=True, limit=64), kinds=kinds,
                               person=person, persona=persona, rules=rules, reason=_text(body, "reason", limit=2000))
        self._audit(project, "autopilot_start", run["id"], person, persona)
        job = self.server.start_job("autopilot", project.pid, ["-m", "kernel.cli", "autopilot", "run", project.pid],
                                    {"person": person, "persona": persona})
        return 201, {"run": run, "job": self.server.job_view(job)}

    def post_autopilot_stop(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """A person stops the autopilot: its delegation is revoked and what it held back is released. Its
        job, if one still runs a pass, delivers nothing more and ends at the pass's next safe point."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        run = kautopilot.stop(project, person=person, persona=persona, reason=_text(body, "reason", limit=2000))
        self._audit(project, "autopilot_stop", run["id"], person, persona)
        job = self.server.running_job(pid)
        ending = None if job is None or job["kind"] != "autopilot" else self.server.job_view(job) | {
            "ending": "the pass under way delivers nothing and ends at its next safe point; a cell already "
                      "working finishes its step first"}
        return 200, {"run": run, "track": ktrack.summary(project), "job": ending}

    def post_delegation_revoke(self, pid: str, did: str, body: dict, **_: object) -> tuple[int, dict]:
        """Stop a delegation at once: its next card waits for a person."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        try:
            d = kdelegation.revoke(project, did, person=person, persona=persona,
                                   reason=_text(body, "reason", limit=2000))
        except KeyError:
            raise ApiError(404, f"no delegation {did} on {pid}") from None
        self._audit(project, "delegation_revoke", did, person, persona)
        return 200, {"delegation": d}

    def post_link(self, **_):
        bootstrap = self.server.issue_link(LINK_TTL)
        return 201, {"url": f"{self.server.origin}/#k={bootstrap}", "expires_in": LINK_TTL}

    # -- the dashboard and the capability layer (the redesigned cockpit) ---------------------------
    # Every read below is a read: it records nothing and appends to no ledger.

    def _products(self) -> list:
        return [p for p in self.factory.projects() if not p.pid.startswith("_")]

    def _factory_canon(self):
        return factory_project(self.factory)

    def _running(self, project) -> bool:
        """Whether a Gnomon cell is running for the project now (kernel.status.live), never a guess."""
        if project.pid == FACTORY_PID:
            return False
        try:
            lv = live(project)
        except Exception:  # noqa: BLE001 - not readable is not running
            return False
        return bool(lv.get("running")) and not lv.get("ended")

    @staticmethod
    def _last_cell(project) -> dict | None:
        """The last cell's outcome from the ledger: the task, round, Gnomon's bucket and when."""
        cells = project.ledger().of_kind("cell_ran")
        if not cells:
            return None
        pl = cells[-1]["event"]["payload"]
        return {"task": pl.get("task"), "round": pl.get("round"), "bucket": pl.get("bucket"),
                "at": cells[-1]["event"].get("at")}

    def _factory_if_any(self):
        """The factory's own canon when it exists; reading never creates it."""
        try:
            return self.factory.project(FACTORY_PID)
        except KeyError:
            return None

    def _autonomy_of(self, project=None) -> dict:
        """kernel.autonomy.describe, read-only: the factory's policy file is read, never created."""
        policy = read_json(self.factory.projects_dir / FACTORY_PID / "policy.json", {}) or {}
        cap = int(policy.get("autonomy_cap", kautonomy.DEFAULT_CAP))
        if project is not None and project.meta.get("autonomy_cap") is not None:
            cap = min(cap, int(project.meta["autonomy_cap"]))
        return {"cap": cap, "name": kautonomy.LEVELS[cap], "meaning": kautonomy.MEANING[cap],
                "levels": [{"level": n, "name": kautonomy.LEVELS[n], "meaning": kautonomy.MEANING[n], "allowed": n <= cap}
                           for n in kautonomy.LEVELS]}

    def _stamp(self) -> str:
        return self.factory.clock.stamp()

    def _decision_items(self) -> list:
        """Every open card a person must decide across the factory: the queue's kinds, plus concepts
        to validate (the factory's canon) and updates to try, with their age.

        Every open change is listed, as the Inbox lists it: a change stays open until a business owner
        or product owner decides it, whether or not its class needs that decision before it is applied
        (``needs_decision`` in the item's payload says which). So the decisions widget and the Inbox
        count the same changes."""
        now_t = self.factory.clock.now()
        items = []
        fp = self._factory_if_any()
        sources = [(p, False) for p in self._products()] + ([(fp, True)] if fp is not None else [])
        for p, is_factory in sources:
            for c in Canon(p).cards(state="open"):
                kind = c["kind"]
                if kind == "question" and not c.get("blocking"):
                    continue
                if is_factory and kind not in ("concept", "approval"):
                    continue
                age = None
                if c.get("created"):
                    try:
                        age = round((now_t - kdash._when(c["created"])).total_seconds() / 3600, 1)
                    except ValueError:
                        age = None
                items.append({"project": p.pid, "project_title": _factory_label(p.pid, p.meta.get("title", p.pid)),
                              "card": c["id"], "kind": kind, "title": self._card_title(c),
                              "deciders": list(deciders_of(c)),
                              "verdicts": list(CARD_VERDICTS[kind]), "age_hours": age,
                              "blocking": bool(c.get("blocking")), "payload": self._card_payload(c)})
        items.sort(key=lambda i: -(i["age_hours"] or 0))
        return items

    @staticmethod
    def _card_payload(c: dict) -> dict:
        """The parts of a card's payload a dashboard shows: a concept's fields, an update's renderings, a
        change's triage (its class, its way back and whether it needs a business decision first)."""
        pl = c.get("payload") or {}
        if c["kind"] == "concept":
            return {k: pl.get(k) for k in ("title", "text", "profile", "profile_basis", "maturity", "mode",
                                           "raised_by", "signal")}
        if c["kind"] == "update":
            return {k: pl.get(k) for k in ("trigger", "facts", "views", "who", "observation")}
        if c["kind"] == "change":
            tri = pl.get("triage") if isinstance(pl.get("triage"), dict) else {}
            return {"source": pl.get("source"), "triaged": bool(tri),
                    **{k: tri.get(k) for k in ("class", "way_back", "needs_decision")}}
        return {}

    def _attestation_of(self, project) -> dict:
        """What an evidence export would attest, computed read-only: the ledger's chain, the Gnomon runs'
        chains, the decisions, and the capability pack (the latest one written, or the release's
        acceptance as it stands). Nothing is built or written."""
        led = project.ledger()
        records = led.records()
        check = led.verify()
        events = [r.get("event") or {} for r in records if isinstance(r, dict)]
        decisions = [e.get("payload") or {} for e in events if e.get("kind") == "decision"]
        runs = [e.get("payload") or {} for e in events if e.get("kind") == "gnomon_run"]
        try:
            pack, latest = _written_pack(project)
        except (KeyError, TypeError, ValueError):
            pack, latest = None, None
        if latest is not None and (pack is None or pack.get("release") != latest.get("release")):
            pack = {"version": None, "release": latest["release"], "acceptance": kpacks.acceptance(project, latest)}
        ev = evidence(project) if project.path("contract.json").exists() else []
        files = {"capability-pack.json": pack or {"note": "no release yet, so no capability pack"},
                 "evidence.json": ev, "decisions.json": decisions,
                 "gnomon-runs.json": [{"chain": r.get("chain")} for r in runs],
                 "ledger-check.json": {"intact": getattr(check, "intact", None),
                                       "broken_seq": getattr(check, "broken_seq", None), "records": len(records)}}
        att = kevidence.attestation(files)
        acc = (pack or {}).get("acceptance") or {}
        return {"project": project.pid, "title": project.meta.get("title"), **att,
                "pack": None if pack is None else {"version": pack.get("version"), "release": pack.get("release"),
                                                   "valid": acc.get("valid"),
                                                   "not_valid_because": acc.get("not_valid_because") or []},
                "decisions": len(decisions), "gates": sum(1 for e in events if e.get("kind") == "gate"),
                "runs": len(runs), "ledger": files["ledger-check.json"], "criteria": len(ev),
                "exports": sum(1 for e in events if e.get("kind") == "evidence_exported")}

    def get_dashboard(self, **_):
        """Every widget's read model in one answer (FR-T1-AC-11): the dashboard is a view of these."""
        f = self.factory
        products = self._products()
        fl = floor(f)
        problems: list = []

        def safe(name, fn, default=None):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - reported per widget, never a crash of the dashboard
                problems.append(f"{name}: {type(exc).__name__}")
                return default

        pipe = safe("pipeline", lambda: kdash.pipeline(f), {"bands": [], "total": 0})
        meta_of = {p.pid: p.meta for p in products}
        for band in pipe.get("bands", []):
            for st in band["stages"]:
                for chip in st["projects"]:
                    m = meta_of.get(chip["id"], {})
                    chip["profile"] = m.get("profile") or kprofiles.DEFAULT_PROFILE
                    chip["paused"] = bool(m.get("pause"))
        rows = []
        for p in products:
            rows.append({"project": p.pid, "title": p.meta.get("title"), "stage": p.meta.get("stage", 1),
                         "maturity": p.meta.get("maturity"),
                         "profile": p.meta.get("profile") or kprofiles.DEFAULT_PROFILE,
                         "now": self._status(now, p, problems), "health": self._status(health, p, problems),
                         "live": safe("live", lambda p=p: live(p), {"running": False, "why": "not read"}),
                         "last_cell": safe("last_cell", lambda p=p: self._last_cell(p))})
        timelines = {}
        for p in products:
            if p.path("contract.json").exists() and len(timelines) < 8:
                tl = safe("timeline", lambda p=p: kdash.timeline(p))
                if tl is not None:
                    timelines[p.pid] = dict(tl, title=p.meta.get("title"))
        decisions = safe("decisions", self._decision_items, [])
        queue = safe("queue", lambda: kdash.queue(f), {"items": [], "count": 0})
        gate_trend = safe("gate_trend", lambda: kdash.gate_trend(f), {"series": [], "rounds": 0, "pass_rate": None})
        coverage = safe("coverage", lambda: kdash.coverage(f), {"projects": [], "total": {}, "proven_share": None})
        catalogue = safe("catalogue", self._catalogue, {"items": [], "counts": {}})
        square = safe("square", lambda: self._square_counts(ksignals.square(f), self._end_user_feedback()), None)
        updates = safe("updates", self._updates, [])
        packs = [safe("evidence_packs", lambda p=p: self._attestation_of(p)) for p in products]
        tries = []
        for p in products:
            t = safe("try_it", lambda p=p: try_it(p))
            if t is not None:
                by_ev: dict = {}
                for it in t.get("items", []):
                    by_ev[it["evidence"]] = by_ev.get(it["evidence"], 0) + 1
                tries.append({"project": p.pid, "title": p.meta.get("title"), "url": t.get("url"),
                              "release": t.get("release"), "env": t.get("env"), "checks": len(t.get("items", [])),
                              "by_evidence": by_ev})
        reliability = safe("models", lambda: model_reliability(f), {})
        g = fl["gates"]
        cov_total = coverage.get("total") or {}
        n_criteria = sum(cov_total.values())
        proven = cov_total.get("verified", 0) + cov_total.get("held_out", 0)
        counts = catalogue.get("counts") or {}
        done = sum(1 for r in rows if (r["now"] or {}).get("state") == "done")
        oldest = max((d["age_hours"] for d in decisions if d["age_hours"] is not None), default=None)
        kpis = {
            "in_flight": {"value": len(products) - done, "of": len(products), "provenance": "observed",
                          "basis": "projects not yet done, of all projects"},
            "decisions": {"value": len(decisions), "oldest_hours": oldest, "provenance": "observed",
                          "basis": "open cards waiting on a person, across projects"},
            "first_round": {"value": g.get("first_round_rate"), "num": g.get("first_round_passed", 0),
                            "of": g.get("tasks_gated", 0), "provenance": "derived",
                            "basis": "tasks that passed their gate on the first round, of tasks gated",
                            "series": [{"at": s["at"], "rate": s["passed"] / (s["passed"] + s["not_passed"])}
                                       for s in gate_trend.get("series", []) if s["passed"] + s["not_passed"]]},
            "proven": {"value": coverage.get("proven_share"), "num": proven, "of": n_criteria,
                       "provenance": "derived",
                       "basis": "criteria verified or held out, of all criteria in compiled contracts"},
            "in_use": {"value": counts.get("in_use", 0), "of": len(catalogue.get("items") or []),
                       "provenance": "observed", "basis": "capabilities in use, of all in the catalogue"},
        }
        return 200, {
            "generated_at": self._stamp(),
            "kpis": kpis,
            "pipeline": pipe,
            "queue": queue,
            "decisions": decisions,
            "gate_trend": gate_trend,
            "gates": g,
            "timelines": timelines,
            "activity": safe("activity", lambda: kdash.activity(f), []),
            "coverage": coverage,
            "catalogue": catalogue,
            "square": square,
            "projects": rows,
            "models": reliability,
            "updates": updates,
            "autonomy": safe("autonomy", self._autonomy_view, None),
            "evidence_packs": [x for x in packs if x is not None],
            "spend": {**fl["spend"], "currency": load_prices().get("currency", "USD"),
                      "runs": fl["overall"].get("runs")},
            "try_it": tries,
            "track": safe("track", lambda: kdash.tracking(f), {"projects": [], "counts": {}, "autopilots": 0}),
            "feed_health": {"measured": False, "why": "no feed probe has reported yet: an integration's freshness "
                                                      "probe writes it once the feed runs"},
            "eval_trend": {"measured": False, "why": "no eval run is recorded over time yet: a model or agent "
                                                     "release's evals appear here once they are re-measured"},
            "problems": problems,
        }

    def _updates(self) -> list:
        """The updates inbox: every update card on every project (open first), with the observation's
        three renderings, and observations that opened no card (inform only)."""
        out = []
        for p in self._products():
            for c in Canon(p).cards(state=None, kind="update"):
                pl = c.get("payload") or {}
                out.append({"project": p.pid, "project_title": p.meta.get("title"), "card": c["id"],
                            "state": c["state"], "title": c["title"], "trigger": pl.get("trigger"),
                            "label": TRIGGERS.get(pl.get("trigger"), {}).get("label"), "views": pl.get("views"),
                            "who": pl.get("who") or list(CARD_DECIDERS["update"]), "decision": c.get("decision"),
                            "created": c.get("created"), "verdicts": list(CARD_VERDICTS["update"])})
        # kernel.observations reads through the factory's canon and would create it: a read never does
        for obs in observations(self.factory) if self._factory_if_any() is not None else []:
            touched = obs.get("touched") or []
            for t in touched:
                if t.get("card") is None:
                    out.append({"project": t.get("project"), "project_title": None, "card": None, "state": "inform",
                                "title": (t.get("views") or {}).get("business"), "trigger": obs.get("trigger"),
                                "label": obs.get("label"), "views": t.get("views"), "who": [], "decision": None,
                                "created": obs.get("at"), "verdicts": []})
            if not touched and obs.get("views"):
                out.append({"project": None, "project_title": None, "card": None, "state": "inform",
                            "title": obs["views"].get("business"), "trigger": obs.get("trigger"),
                            "label": obs.get("label"), "views": obs.get("views"), "who": [], "decision": None,
                            "created": obs.get("at"), "verdicts": []})
        out.sort(key=lambda u: u["created"] or "", reverse=True)
        out.sort(key=lambda u: {"open": 0, "inform": 1}.get(u["state"], 2))
        return out

    def _autonomy_view(self) -> dict:
        fac = self._autonomy_of()
        projects = []
        for p in self._products():
            d = self._autonomy_of(p)
            projects.append({"project": p.pid, "title": p.meta.get("title"), "cap": d["cap"], "name": d["name"],
                             "own": p.meta.get("autonomy_cap")})
        history = []
        for p in [x for x in [self._factory_if_any()] if x is not None] + self._products():
            for r in p.ledger().of_kind("autonomy_cap_set"):
                pl = r["event"]["payload"]
                history.append({"project": None if p.pid == FACTORY_PID else p.pid,
                                **{k: pl.get(k) for k in ("scope", "from", "to", "by", "persona", "reason")},
                                "at": r["event"].get("at")})
        history.sort(key=lambda x: x["at"] or "", reverse=True)
        return {"factory": fac, "projects": projects, "setters": list(kautonomy.SETTERS), "history": history[:20]}

    def _catalogue(self) -> dict:
        """kernel.dashboard.catalogue, with what a reader needs to say it right: a proposed concept's
        deliverable is its work profile's (an agent concept is a capability pack, not a product), and a
        project's releases, so a pack not built yet is never called "no release". Read only."""
        from kernel.deliver import releases

        cat = kdash.catalogue(self.factory)
        for item in cat.get("items") or []:
            if not item.get("deliverable"):
                item["deliverable"] = (kprofiles.PROFILES.get(item.get("profile")) or {}).get("deliverable", "product")
            if item.get("project"):
                try:
                    rels = releases(self.factory.project(item["project"]))
                except (KeyError, OSError, TypeError, ValueError):
                    rels = []
                item["releases"] = len(rels)
                item["latest_release"] = rels[-1].get("release") if rels and isinstance(rels[-1], dict) else None
        return cat

    def get_catalogue(self, **_):
        """The capability catalogue (FR-T1-AC-14): what each capability is, what it delivers, how far it is."""
        cat = self._catalogue()
        return 200, {**cat, "states": list(kdash.CATALOGUE_STATES), "profiles": kprofiles.public(),
                     "deliverables": dict(kprofiles.DELIVERABLES)}

    def _people_by_corner(self) -> dict:
        """Who works in each corner of the delivery square, from the decisions and signals people signed."""
        corner_of = {"stakeholder": "needs", "business_owner": "concept", "product_owner": "concept",
                     "concept_evaluator": "concept", "developer": "factory", "end_user": "testing",
                     "operations": "production", "it": "production", "compliance": "production"}
        people: dict = {k: {} for k in ("needs", "concept", "factory", "testing", "production")}
        for s in ksignals.signals(self.factory):
            if s.get("person") and is_person(s["person"]):
                # the persona the signal was signed with; one nobody's persona raised is a stakeholder's
                people["needs"].setdefault(s["person"], s.get("persona") if s.get("persona") in PERSONAS
                                           else "stakeholder")
        for p in self._products():
            for c in Canon(p).cards(state=None, kind="change"):
                pl = c.get("payload") or {}
                if pl.get("source") == "end_user" and is_person(pl.get("person")) and "embed" not in str(pl.get("person")):
                    people["testing"].setdefault(pl["person"], "end_user")
        for p in self.factory.projects():
            for d in Canon(p).decisions():
                corner = corner_of.get(d.get("persona"))
                if corner and is_person(d.get("person")):
                    people[corner].setdefault(d["person"], d["persona"])
        return {k: [{"name": n, "persona": v} for n, v in list(d.items())[:8]] for k, d in people.items()}

    def _end_user_feedback(self) -> list:
        """Every change an end user filed, on every product: open first, then the newest."""
        feedback = []
        for p in self._products():
            for c in Canon(p).cards(state=None, kind="change"):
                pl = c.get("payload") or {}
                if pl.get("source") == "end_user":
                    feedback.append({"project": p.pid, "project_title": p.meta.get("title"), "card": c["id"],
                                     "title": c["title"], "state": c["state"], "triaged": bool(pl.get("triage")),
                                     "person": pl.get("person"), "created": c.get("created")})
        feedback.sort(key=lambda x: x["created"] or "", reverse=True)
        feedback.sort(key=lambda x: x["state"] != "open")
        return feedback

    @staticmethod
    def _square_counts(sq: dict, feedback: list) -> dict:
        """The square's counts as the cockpit shows them. The end-user testing corner says how much
        feedback waits, so ``end_user_feedback_waiting`` counts every open end-user report: one not
        triaged yet waits for its class, a triaged one waits on a decision (a report filed in the
        cockpit is triaged at once). The kernel's own count, the reports not triaged yet, is
        ``end_user_feedback_untriaged``."""
        open_ = sum(1 for x in feedback if x["state"] == "open")
        return {**sq, "end_user_feedback_untriaged": sq.get("end_user_feedback_waiting", 0),
                "end_user_feedback_waiting": open_, "end_user_feedback_open": open_}

    def get_square(self, query: dict | None = None, **_):
        """The delivery square at a glance (kernel.signals.square), with what sits in each corner.
        ``signals_list`` holds every signal still new and the newest others up to SQUARE_SIGNALS, newest
        first, so a new signal can always be triaged; ``?signals=all`` lists every signal. ``?show=S-8,...``
        also lists the signals named (up to SQUARE_SHOWN), such as one the person just triaged that is no
        longer new nor among the newest: ``signals_shown`` names those listed only for that reason."""
        f = self.factory
        query = query or {}
        sq = ksignals.square(f)
        fp = self._factory_if_any()          # read, never created here
        concepts = [dict(self._card_payload(c), card=c["id"], created=c.get("created"), card_title=self._card_title(c),
                         body=c.get("body"), deciders=list(CARD_DECIDERS["concept"]))
                    for c in (Canon(fp).cards(kind="concept") if fp is not None else [])]
        newest_first = ksignals.signals(f)[::-1]
        every = query.get("signals") == "all"
        named = {x for x in str(query.get("show") or "").split(",")[:SQUARE_SHOWN] if SIGNAL_ID_RE.match(x)}
        listed, shown = [], []
        for i, s in enumerate(newest_first):
            if every or i < SQUARE_SIGNALS or s.get("state") == "new":
                listed.append(s)
            elif s.get("id") in named:
                listed.append(s)
                shown.append(s["id"])
        feedback, production = self._end_user_feedback(), []
        for p in self._products():
            if p.meta.get("stage") == 7:
                production.append({"project": p.pid, "title": p.meta.get("title"), "now": self._status(now, p),
                                   "health": self._status(health, p),
                                   "profile": p.meta.get("profile") or kprofiles.DEFAULT_PROFILE})
        return 200, {**self._square_counts(sq, feedback), "signals_list": listed, "signals_shown": shown,
                     "signals_all": every or len(listed) == len(newest_first), "concepts": concepts,
                     "feedback": feedback[:40], "production": production, "people": self._people_by_corner(),
                     "channels": list(ksignals.CHANNELS)}

    def get_signals(self, query: dict, **_):
        state = query.get("state") or None
        if state is not None and state not in ksignals.STATES:
            raise ApiError(400, f"state must be one of {', '.join(ksignals.STATES)}")
        return 200, {"signals": ksignals.signals(self.factory, state), "channels": list(ksignals.CHANNELS),
                     "states": list(ksignals.STATES)}

    def get_profiles(self, **_):
        return 200, {"profiles": kprofiles.public(), "deliverables": dict(kprofiles.DELIVERABLES),
                     "default": kprofiles.DEFAULT_PROFILE}

    def post_profile_propose(self, body: dict, **_):
        """The profile Rihma proposes for a request, by rule over its words. It records nothing."""
        text = _text(body, "text", required=True, limit=200_000)
        return 200, kprofiles.propose_profile(text)

    def get_inbox_all(self, query: dict, **_):
        """Every open card the persona may decide, across every project and the factory's own canon."""
        persona = query.get("persona", "")
        if persona not in PERSONAS:
            raise ApiError(400, f"persona must be one of {', '.join(PERSONAS)}")
        cards = []
        for p in self.factory.projects():
            canon = Canon(p)
            for c in canon.cards(state="open", persona=persona):
                view = self._card_view(c, canon)
                view["project"] = p.pid
                view["project_title"] = _factory_label(p.pid, p.meta.get("title", p.pid))
                cards.append(view)
        return 200, {"persona": persona, "cards": cards, "count": len(cards)}

    def get_ui_map(self, **_):
        return 200, kassistant.ui_map()

    def get_timeline(self, pid: str, **_):
        """Each task's rounds with start, end and verdict, merges and escalations (kernel.dashboard)."""
        return 200, kdash.timeline(self._project(pid))

    def get_context(self, pid: str, query: dict, **_):
        """The lens this persona starts in (or the one asked for) and the views in the order the project's
        stage and that lens bring them forward, with the project's work profile (FR-T1-AC-12)."""
        project = self._project(pid)
        persona = query.get("persona", "")
        if persona not in PERSONAS:
            raise ApiError(400, f"persona must be one of {', '.join(PERSONAS)}")
        lens = query.get("lens") or None
        if lens is not None and lens not in LENSES:
            raise ApiError(400, f"lens must be one of {', '.join(LENSES)}")
        ctx = project_context(project, persona, lens)
        ctx["default_lens"] = lens_for(persona)
        ctx["views"] = [v for v in ctx["views"] if kmodules.shown(project, "views", v)]   # only what is enabled
        return 200, ctx

    # layouts: per person, persona and lens, in the cockpit's own folder, never in a project ledger

    def _layout_path(self, person: str, persona: str, lens: str) -> Path:
        import hashlib

        key = hashlib.sha256(person.strip().encode("utf-8")).hexdigest()[:20]
        return self.server.layouts_dir / key / persona / f"{lens}.json"

    @staticmethod
    def _preset(lens: str) -> dict:
        return {"v": 1, "lens": lens, "widgets": [{"id": f"{t}-{i + 1}", "type": t, "size": s,
                                                   "view": "list" if t in LIST_FIRST else "chart", "filter": {}}
                                                  for i, (t, s) in enumerate(LENS_DEFAULTS[lens])]}

    def _layout_for(self, person: str, persona: str, lens: str) -> tuple:
        if person and is_person(person) and persona in PERSONAS:
            saved = read_json(self._layout_path(person, persona, lens))
            if isinstance(saved, dict) and isinstance(saved.get("layout"), dict):
                return saved["layout"], False
        return self._preset(lens), True

    @staticmethod
    def _who_lens(query: dict) -> tuple:
        persona = query.get("persona", "")
        if persona not in PERSONAS:
            raise ApiError(400, f"persona must be one of {', '.join(PERSONAS)}")
        lens = query.get("lens") or lens_for(persona)
        if lens not in LENSES:
            raise ApiError(400, f"lens must be one of {', '.join(LENSES)}")
        return (query.get("person") or "").strip(), persona, lens

    def get_layout(self, query: dict, **_):
        person, persona, lens = self._who_lens(query)
        layout, preset = self._layout_for(person, persona, lens)
        return 200, {"layout": layout, "preset": preset, "default": self._preset(lens), "lens": lens,
                     "persona": persona}

    @staticmethod
    def _check_layout(layout, lens: str) -> dict:
        """A layout is versioned JSON within fixed boundaries: known widget types, at most 24 widgets,
        sizes and views from fixed sets, a small filter object, and theme values from fixed sets."""
        if not isinstance(layout, dict) or layout.get("v") != 1:
            raise ApiError(400, "a layout is an object with v: 1")
        if layout.get("lens", lens) != lens:
            raise ApiError(400, "the layout's lens is not the lens it is saved for")
        widgets = layout.get("widgets")
        if not isinstance(widgets, list):
            raise ApiError(400, "widgets must be a list")
        if len(widgets) > MAX_WIDGETS:
            raise ApiError(400, f"a layout holds at most {MAX_WIDGETS} widgets")
        clean, ids = [], set()
        for w in widgets:
            if not isinstance(w, dict):
                raise ApiError(400, "each widget is an object with id, type, size, view and filter")
            wtype = w.get("type")
            if wtype not in WIDGETS:
                raise ApiError(400, f"unknown widget type {str(wtype)[:40]!r}")
            wid = w.get("id")
            if not isinstance(wid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", wid) or wid in ids:
                raise ApiError(400, "each widget needs a unique id of letters, digits, - or _")
            ids.add(wid)
            size = w.get("size", "M")
            if size not in kassistant.SIZES:
                raise ApiError(400, f"size must be one of {', '.join(kassistant.SIZES)}")
            view = w.get("view", "chart")
            if view not in LAYOUT_VIEWS:
                raise ApiError(400, f"view must be one of {', '.join(LAYOUT_VIEWS)}")
            filt = w.get("filter") or {}
            plain = (str, int, float, bool, type(None))
            if not isinstance(filt, dict) or len(json.dumps(filt)) > 400 or \
                    not all(isinstance(k, str) and isinstance(v, plain) for k, v in filt.items()):
                raise ApiError(400, "filter is a small object of plain values")
            clean.append({"id": wid, "type": wtype, "size": size, "view": view, "filter": filt})
        out = {"v": 1, "lens": lens, "widgets": clean}
        theme = layout.get("theme")
        if theme is not None:
            why = kassistant.check_theme(theme)
            if why:
                raise ApiError(400, f"theme: {why}")
            out["theme"] = dict(theme)
        return out

    def put_layout(self, query: dict, body: dict, **_):
        """Save a person's layout for a persona and a lens (FR-T1-AC-11). It is the cockpit's own file
        under the factory home's _cockpit/layouts/, never written into any project's ledger."""
        _, persona, lens = self._who_lens(query)
        person, persona = self._sign(_text(body, "person", limit=200), persona, None)   # a persona granted anywhere
        if not is_person(person):
            raise ApiError(403, f"refused: {person!r} is not a person; a layout belongs to a named person")
        layout = self._check_layout(body.get("layout"), lens)
        write_json(self._layout_path(person, persona, lens), {"person": person, "persona": persona, "lens": lens,
                                                               "saved": self._stamp(), "layout": layout})
        return 200, {"layout": layout, "preset": False, "lens": lens, "persona": persona}

    # signals and concepts: the delivery square's front corner

    def post_signal(self, body: dict, **_):
        person, persona = self._who(body, FACTORY_PID)
        _require_person(person, persona)
        text = _text(body, "text", required=True, limit=ksignals.MAX_TEXT)
        channel = _text(body, "channel", limit=32) or "manual"
        source = _text(body, "source", limit=200) or "the cockpit"
        try:
            # The signal keeps its signer's persona: triage routes by it (IT's need is an infra change).
            s = ksignals.receive(self.factory, text, channel=channel, source=source, person=person, persona=persona)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        self._audit(self._factory_canon(), "log_signal", s["id"], person, persona)
        return 201, {"signal": s}

    def post_signal_triage(self, sid: str, body: dict, **_):
        person, persona = self._who(body, FACTORY_PID)
        _require_person(person, persona)
        try:
            s = ksignals.triage(self.factory, sid, model=None)
        except KeyError:
            raise ApiError(404, f"no signal {sid}") from None
        except ValueError as exc:
            raise ApiError(409, str(exc)) from None
        out = {"signal": s}
        routed = s.get("routed_to") or {}
        if s["state"] == "routed" and routed.get("project") and routed.get("card"):
            # A change routed to a project is triaged at once, like every change filed in the cockpit:
            # it gets its class, its way back and its impact, and reaches the decisions that wait.
            # The signal is routed already; a triage that cannot be written leaves the change untriaged.
            try:
                out["triage"] = triage(self.factory.project(routed["project"]), routed["card"], model=None)
            except (OSError, KeyError, ValueError) as exc:
                out["triage"], out["triage_error"] = None, type(exc).__name__
        self._audit(self._factory_canon(), "triage_signal", sid, person, persona, state=s["state"])
        return 200, out

    def _open_concept(self, cid: str) -> dict | None:
        """The open concept card ``cid`` on the factory's canon, read only; None when there is none (the
        kernel then refuses the edit with its own reason)."""
        fp = self._factory_if_any()
        try:
            card = Canon(fp).get_card(cid) if fp is not None else None
        except (KeyError, ValueError, OSError):
            return None
        return card if card and card.get("kind") == "concept" and card.get("state") == "open" else None

    def post_concept_edit(self, cid: str, body: dict, **_):
        person, persona = self._who(body, FACTORY_PID)
        fields = {}
        for k in ("title", "profile", "maturity", "mode"):
            if body.get(k) not in (None, ""):
                fields[k] = _text(body, k, limit=200)
        if not fields:
            raise ApiError(400, "send a title, profile, maturity or mode to change")
        card = self._open_concept(cid)
        if card is not None:
            # Only what the person changed is an edit: an unchanged field is neither written nor recorded.
            current = card.get("payload") or {}
            fields = {k: v for k, v in fields.items() if str(current.get(k) or "") != (v[:80] if k == "title" else v)}
            if not fields:
                if not is_person(person) or persona not in CARD_DECIDERS["concept"]:
                    raise DecisionRefused(f"a {persona or 'nobody'} named {person!r} may not edit a concept")
                return 200, {"card": card, "changed": []}
        try:
            card = ksignals.edit_concept(self.factory, cid, person=person, persona=persona, **fields)
        except KeyError:
            raise ApiError(404, f"no concept {cid}") from None
        except DecisionRefused:
            raise
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        self._audit(self._factory_canon(), "edit_concept", cid, person, persona, fields=sorted(fields))
        return 200, {"card": card, "changed": sorted(fields)}

    # comments: people talk about the work without deciding anything

    def get_comments(self, pid: str, query: dict, **_):
        canon = Canon(self._project(pid))
        kind, tid = query.get("kind"), query.get("id")
        target = {"kind": kind, "id": tid} if kind and tid else None
        return 200, {"comments": canon.comments(target), "targets": list(Canon.COMMENT_TARGETS),
                     "promoters": list(PROMOTERS)}

    def post_comment(self, pid: str, body: dict, **_):
        project = self._project(pid)
        person, persona = self._who(body, pid)
        target = body.get("target")
        text = _text(body, "text", limit=4000)
        if not isinstance(target, dict):
            raise ApiError(400, f"target is an object: one of {', '.join(Canon.COMMENT_TARGETS)} with an id")
        try:
            c = Canon(project).comment({"kind": target.get("kind"), "id": str(target.get("id") or "")[:80]}, text,
                                       person=person, persona=persona)
        except DecisionRefused:
            raise
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        self._audit(project, "comment", c["id"], person, persona)
        return 201, {"comment": c}

    def post_comment_promote(self, pid: str, cmid: str, body: dict, **_):
        project = self._project(pid)
        person, persona = self._who(body, pid)
        if not is_person(person):
            raise DecisionRefused(f"{person!r} is not a person")
        try:
            card = Canon(project).promote_comment(cmid, person=person, persona=persona)
        except KeyError:
            raise ApiError(404, f"no comment {cmid}") from None
        except DecisionRefused:
            raise
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        result = triage(project, card["id"], model=None)
        self._audit(project, "promote_comment", cmid, person, persona, card=card["id"])
        canon = Canon(project)
        return 201, {"card": self._card_view(canon.get_card(card["id"]), canon), "triage": result}

    # autonomy: the ladder, capped by a person with a reason

    def get_autonomy(self, **_):
        return 200, {**self._autonomy_view(),
                     "levels": {str(n): {"name": kautonomy.LEVELS[n], "meaning": kautonomy.MEANING[n]}
                                for n in kautonomy.LEVELS}}

    def _set_cap(self, target, body: dict, pid: str) -> tuple[dict, str, str]:
        person, persona = self._who(body, pid)
        level = body.get("level")
        if isinstance(level, bool) or not isinstance(level, int):
            raise ApiError(400, "level is a whole number from 1 to 4")
        reason = _text(body, "reason", limit=2000)
        try:
            return kautonomy.set_cap(target, level, person=person, persona=persona, reason=reason), person, persona
        except DecisionRefused:
            raise
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None

    def put_autonomy(self, body: dict, **_):
        out, person, persona = self._set_cap(self.factory, body, FACTORY_PID)
        self._audit(self._factory_canon(), "set_autonomy_cap", "factory", person, persona, level=out["cap"])
        return 200, {**out, "autonomy": self._autonomy_view()}

    def put_project_autonomy(self, pid: str, body: dict, **_):
        project = self._project(pid)
        if pid == FACTORY_PID:
            raise ApiError(400, "set the factory's cap with PUT /api/autonomy")
        out, person, persona = self._set_cap(project, body, pid)
        self._audit(project, "set_autonomy_cap", pid, person, persona, level=out["cap"])
        return 200, {**out, "autonomy": self._autonomy_view()}

    # modules: the parts of Rihmasto in use, chosen by a person (kernel/modules.py, FR-MOD1)

    def get_modules(self, **_: object) -> tuple[int, dict]:
        return 200, kmodules.view(self.factory)

    def _set_modules(self, target: Factory | Project, body: dict, pid: str) -> dict:
        person, persona = self._who(body, pid)
        listed = body.get("modules")
        if listed is not None and not (isinstance(listed, list) and all(isinstance(m, str) for m in listed)):
            raise ApiError(400, "modules is a list of module ids")
        preset = _text(body, "preset", limit=64) or None
        out = kmodules.set_modules(target, person=person, persona=persona, preset=preset, modules=listed,
                                   inherit=body.get("inherit") is True, reason=_text(body, "reason", limit=2000))
        return out | {"view": kmodules.view(self.factory)}

    def put_modules(self, body: dict, **_: object) -> tuple[int, dict]:
        return 200, self._set_modules(self.factory, body, FACTORY_PID)

    def put_project_modules(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        if pid == FACTORY_PID:
            raise ApiError(400, "choose the factory's modules with PUT /api/modules")
        return 200, self._set_modules(self._project(pid), body, pid)

    # postures: how a project runs, previewed before anyone chooses (kernel/posture.py)

    def get_postures(self, **_: object) -> tuple[int, dict]:
        return 200, kposture.public()

    def post_posture_preview(self, body: dict, **_: object) -> tuple[int, dict]:
        """What a posture and its weights would do, by the kernel's rules; with ``project``, also what
        changing that project to it would change now and later. It records nothing."""
        from kernel.posture_change import proposed, what_changes

        name = _text(body, "posture", required=True, limit=32)
        weights, maturity = _weights_in(body), _text(body, "maturity", limit=32) or None
        mode, pid = _text(body, "mode", limit=32) or None, _text(body, "project", limit=81) or None
        if pid is None:
            return 200, kposture.preview(name, weights, maturity=maturity, mode=mode,
                                         profile=_text(body, "profile", limit=64) or None)
        project = self._project(pid)
        after = proposed(project, name, weights, maturity=maturity, mode=mode)
        return 200, {**kposture.preview(name, weights, maturity=after["maturity"], mode=mode,
                                        profile=project.meta.get("profile")), **what_changes(project, after)}

    def get_posture(self, pid: str, **_: object) -> tuple[int, dict]:
        """A project's posture: what it does, what holds the project now, and the autonomy cap. The
        factory's own canon takes none, and says so."""
        from kernel.posture_rules import view

        if pid == FACTORY_PID:
            return 200, {"project": pid, "posture": None, "note": "the factory's own canon takes no posture"}
        return 200, {"project": pid, **view(self._project(pid))}

    def put_posture(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """A person chooses or changes the project's posture during the run, with a reason. The kernel
        decides whether it stands and says what it changes now and later."""
        from kernel.posture_change import change

        project = self._project(pid)
        person, persona = self._who(body, pid)
        out = change(project, _text(body, "posture", required=True, limit=32), _weights_in(body), person=person,
                     persona=persona, reason=_text(body, "reason", limit=2000),
                     maturity=_text(body, "maturity", limit=32) or None, mode=_text(body, "mode", limit=32) or None)
        self._audit(project, "set_posture", pid, person, persona, posture=out["posture"])
        return 200, out

    # capability packs and evidence packs

    def get_pack(self, pid: str, **_: object) -> tuple[int, dict]:
        """The capability pack as last written, with its YAML view: reading never builds one, so it never
        records a version. ``pack`` is null while the latest release has none (build it with POST
        .../pack/build). 404 while the project has no release."""
        project = self._project(pid)
        try:
            pack, latest = _written_pack(project)
        except (KeyError, TypeError) as exc:
            raise ApiError(409, f"the release record could not be read: {type(exc).__name__}") from None
        if latest is None:
            raise ApiError(404, f"{pid} has no release yet, so no capability pack")
        return 200, self._pack_view(project, pack, latest)

    @staticmethod
    def _pack_view(project: Project, pack: dict | None, latest: dict) -> dict:
        current = pack is not None and pack.get("release") == latest.get("release")
        return {"pack": pack, "yaml": kpacks.render_yaml(pack) if pack else None,
                "history": project.read("packs.json", []) or [], "latest_release": latest.get("release"),
                "current": current, "builders": list(PACK_BUILDERS),
                "note": None if current else f"release {latest.get('release')} has no capability pack yet: building "
                                             f"one records its version in packs.json and the ledger"}

    def post_pack_build(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """Build the latest release's capability pack: an explicit write, signed by a person whose persona
        exports evidence. The kernel keeps the version while the content is the same; a new content is a
        new version, in packs.json and the ledger."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        _require_person(person, persona)
        if persona not in PACK_BUILDERS:
            raise DecisionRefused(f"a {persona} may not build a capability pack; {', '.join(PACK_BUILDERS)} may")
        try:
            pack = kpacks.build_pack(project)
        except LookupError:
            raise ApiError(404, f"{pid} has no release yet, so no capability pack") from None
        except (KeyError, TypeError) as exc:
            raise ApiError(409, f"the release record could not be read: {type(exc).__name__}") from None
        self._audit(project, "build_pack", f"release {pack['release']}", person, persona, version=pack["version"])
        return 200, self._pack_view(project, pack, {"release": pack["release"]})

    def get_attestation(self, pid: str, **_):
        """What an evidence export would attest, read-only: attestable, chain broken or insufficient
        evidence, never 'compliant', with the control table."""
        return 200, self._attestation_of(self._project(pid))

    # the assessment of an adopted system, from every perspective (kernel/assess.py, kernel/assess_cards.py)

    def get_assessment(self, pid: str, **_):
        project = self._project(pid)
        with self.server._jobs_lock:
            run = dict(self.server.assessing.get(pid) or {}) or None
        return 200, {**kassess_cards.view(project), "run": run,
                     "panel_available": self.server.assistant_model is not None}

    def post_assessment(self, pid: str, body: dict, **_):
        """Assess the project's repository, signed by whoever asks. By rule it takes seconds and is recorded
        before the answer (201). With ``panel: true`` the panel's perspectives speak through the cockpit's
        own model, which takes minutes: it runs in the background (202) and GET shows its end."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        _require_person(person, persona)
        model = self.server.assistant_model if body.get("panel") is True else None
        if body.get("panel") is True and model is None:
            raise ApiError(409, "the cockpit has no model (its assistant answers from the map), so the panel "
                                f"cannot review: assess by the rules, or run `rihmasto assess {pid} --with-model`")
        kassess.mirror(project)        # no repository: refused before anything starts
        run = {"state": "running", "started": self.factory.clock.stamp(), "person": person, "persona": persona,
               "panel": model is not None}
        with self.server._jobs_lock:
            if (self.server.assessing.get(pid) or {}).get("state") == "running":
                raise ApiError(409, f"an assessment of {pid} is still running")
            self.server.assessing[pid] = run
        self._audit(project, "assess", pid, person, persona, panel=run["panel"])
        if model is None:
            self.server.run_assessment(project, run, None, self.identity)
            if run["state"] != "done":
                raise ApiError(500, f"the assessment failed: {run.get('error')}")
            return 201, {"run": dict(run), "assessment": kassess.summary(kassess.load(project, run["id"]))}
        threading.Thread(target=self.server.run_assessment, args=(project, run, model, self.identity),
                         name=f"assess-{pid}", daemon=True).start()
        return 202, {"run": dict(run)}

    def post_assessment_changes(self, pid: str, body: dict, **_):
        """File chosen findings of an assessment as change cards, signed by the person who files them."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        _require_person(person, persona)
        ids, version = body.get("findings"), body.get("version")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ApiError(400, "findings is a list of finding ids, such as F-2 and P-1")
        if version is not None and (isinstance(version, bool) or not isinstance(version, int | str)):
            raise ApiError(400, "version is an assessment's number or id, such as AS-2")
        try:
            out = kassess_cards.to_changes(project, ids, person=person, persona=persona, version=version,
                                           as_class=_text(body, "as", limit=32) or kassess.CLASS_DEFAULT)
        except LookupError as exc:
            raise ApiError(404, str(exc.args[0] if exc.args else exc)) from None
        self._audit(project, "assessment_changes", out["assessment"], person, persona,
                    cards=[c["card"] for c in out["opened"]])
        return 201, out

    def post_evidence_export(self, pid: str, body: dict, **_):
        """Export the evidence pack into _cockpit/exports/ and hand back a one-time download path."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        path = kevidence.export(project, self.server.exports_dir, person=person, persona=persona)
        token = self.server.offer_download(path.name)
        self._audit(project, "export_evidence", path.name, person, persona)
        return 201, {"file": path.name, "download": f"/api/exports/{token}", "expires_in": EXPORT_TTL,
                     "attestation": self._attestation_of(project)}

    def get_export(self, token: str, **_):
        path = self.server.take_download(token)
        if path is None:
            raise ApiError(404, "this download link was already used, has expired, or names no export")
        return 200, FileResponse(path)

    # outputs per audience (kernel/outputs.py): the kernel records each choice and build with its person

    @staticmethod
    def _intake_outputs(body: dict, persona: str) -> list[str]:
        """The outputs a new project's request names, chosen at intake; refused before the project is made when
        the requester's persona may not choose them."""
        outputs = koutputs.known_targets(body.get("outputs") or [])
        if outputs and persona not in koutputs.CHOOSERS:
            raise DecisionRefused(f"a {persona} may not choose outputs; {', '.join(koutputs.CHOOSERS)} may")
        return outputs

    def get_outputs(self, pid: str, **_: object) -> tuple[int, dict]:
        return 200, koutputs.view(self._project(pid))

    def put_outputs(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        person, persona = self._who(body, pid)
        return 200, koutputs.choose(self._project(pid), body.get("targets"), person=person, persona=persona,
                                    reason=_text(body, "reason", limit=500))

    def post_outputs_build(self, pid: str, body: dict, **_: object) -> tuple[int, dict]:
        """Build the chosen targets into the exports folder; each built file is offered as a one-time download."""
        project = self._project(pid)
        person, persona = self._who(body, pid)
        out = koutputs.build(project, body.get("targets"), self.server.exports_dir, person=person, persona=persona)
        for row in out["outputs"]:
            row["files"] = sorted(row.get("files") or [])
            if row.get("file"):
                row["download"] = f"/api/exports/{self.server.offer_download(row['file'])}"
        return 201, {**out, "expires_in": EXPORT_TTL, "view": koutputs.view(project)}

    # embeds: a chat window for a website, with exactly one capability

    def _embed_base_view(self) -> dict:
        """Where an embed's snippet points: the embed server's configured address, or the local embed
        server for testing while none is set. Never the cockpit, which serves no widget."""
        return {"embed_base": self.server.embed_base, "embed_base_local": kembeds.LOCAL_EMBED_BASE,
                "embed_base_env": kembeds.EMBED_BASE_ENV}

    def get_embeds(self, **_):
        items = [kembeds.public(e) for e in kembeds.embeds(self.factory)]
        for e in items:
            e.pop("key", None)
        return 200, {"embeds": items[::-1], "kinds": list(kembeds.KINDS), "creators": list(kembeds.CREATORS),
                     **self._embed_base_view()}

    def post_embed(self, body: dict, **_):
        person, persona = self._who(body, FACTORY_PID)
        kind = _text(body, "kind", limit=32)
        origins = body.get("origins")
        if isinstance(origins, str):
            origins = [o for o in re.split(r"[\s,]+", origins) if o]
        if not isinstance(origins, list) or len(origins) > 20 or not all(isinstance(o, str) for o in origins):
            raise ApiError(400, "origins is a list of up to 20 website addresses")
        project_id = _text(body, "project", limit=100) or None
        if kind == "feedback" and project_id is not None and project_id.startswith("_"):
            # Feedback is on a product. Rihma's own canon takes no anonymous website's word as a change.
            raise ApiError(400, "a feedback embed belongs to a product; Rihma itself takes no website feedback")
        if project_id is not None:   # a feedback embed files changes on its project: granted there too
            person, persona = self._sign(person, persona, project_id)
        try:
            e = kembeds.create(self.factory, kind=kind, origins=origins, person=person, persona=persona,
                               project_id=project_id, label=_text(body, "label", limit=80),
                               brief=_text(body, "brief", limit=600))
        except KeyError:
            raise ApiError(404, f"no project {project_id}") from None
        except DecisionRefused:
            raise
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        key = e.pop("key")
        self._audit(self._factory_canon(), "create_embed", e["id"], person, persona)
        return 201, {"embed": kembeds.public(e), "key": key, "snippet": kembeds.snippet(e, self.server.embed_base, key),
                     "shown_once": True, **self._embed_base_view()}

    def post_embed_revoke(self, eid: str, body: dict, **_):
        person, persona = self._who(body, FACTORY_PID)
        held = next((e for e in kembeds.embeds(self.factory) if e.get("id") == eid), None)
        if held is not None and held.get("state") == "revoked" and is_person(person) and persona in kembeds.CREATORS:
            # Already stopped: a second revoke records nothing (writes run one at a time under the lock).
            raise ApiError(409, f"{eid} is already revoked")
        try:
            e = kembeds.revoke(self.factory, eid, person=person, persona=persona)
        except KeyError:
            raise ApiError(404, f"no embed {eid}") from None
        self._audit(self._factory_canon(), "revoke_embed", eid, person, persona)
        return 200, {"embed": kembeds.public(e)}

    # the assistant: answers and proposals, never an action

    def post_assistant(self, body: dict, **_):
        """Ask the cockpit assistant (kernel.assistant). The server adds what the person may reshape: the
        widget library and their current layout. The answer may propose actions; it takes none, and
        this route writes nothing. A proposal runs only when the person confirms it, through the
        route its click would use."""
        question = _text(body, "question", required=True, limit=2000)
        persona = _text(body, "persona", limit=64)
        if persona not in PERSONAS:
            raise ApiError(400, f"persona must be one of {', '.join(PERSONAS)}")
        pid = _text(body, "project", limit=100) or None
        if pid is not None:
            self._project(pid)
        lens = _text(body, "lens", limit=32) or lens_for(persona)
        if lens not in LENSES:
            raise ApiError(400, f"lens must be one of {', '.join(LENSES)}")
        person, persona = self._sign(_text(body, "person", limit=200), persona, pid)
        layout, _ = self._layout_for(person, persona, lens)
        where = self.factory.project(pid) if pid else self.factory      # the widgets and the model it may use
        ui = {"widgets": [w for w in WIDGETS if kmodules.shown(where, "widgets", w)], "layout": layout}
        try:
            out = kassistant.ask(self.factory, question, persona=persona, project_id=pid,
                                 view=_text(body, "view", limit=64) or None, ui=ui,
                                 model=self.server.assistant_model if kmodules.is_on(where, "assistant") else None)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        out["lens"] = lens
        return 200, out


# -- entry points ---------------------------------------------------------------------------------

def make_server(factory: Factory, port: int = 0, *, runner=None, host: str = LOOPBACK, assistant_model=None,
                embed_base: str | None = None):
    """Build the cockpit server on 127.0.0.1 (port 0: any free port) and its first one-use
    sign-in bootstrap. Any other host is refused. ``assistant_model`` is the assistant's model
    (a ``kernel.model.Model``); without one the assistant answers from the cockpit's map.
    ``embed_base`` is the embed server's public address, which embed snippets point at; without
    one they point at the local embed server, for testing."""
    if host != LOOPBACK:
        raise ValueError(f"the cockpit binds to {LOOPBACK} only, not {host!r}; reach it through an SSH tunnel")
    server = CockpitServer(factory, port, runner, assistant_model=assistant_model, embed_base=embed_base)
    kaccess.load(factory, record=True, by="the cockpit")   # a changed access file is on record from the start
    return server, server.issue_link(ttl=None)


def access_note(factory: Factory) -> str:
    """The line the server prints at start: the access mode (kernel.access, D-0016)."""
    access = kaccess.load(factory)
    if not access.enforced:
        return f"Access: {kaccess.SINGLE_NOTE}. Whoever holds the session picks the person and the persona."
    if access.error or access.proxy is None:
        return f"Access: enforced, but {access.error}: every request is refused until IT fixes it."
    keys = f"; but {access.keys_error}, so nobody signs in yet" if access.keys_error else ""
    return (f"Access: enforced. People sign in at {access.proxy.origin} through IT's proxy ({access.proxy.preset}), "
            f"whose signed token the cockpit verifies{keys}; the printed link is not needed. Untrusted code: "
            f"{kisolation.describe(access)}.")


def configured_embed_base(flag: str | None, environ: Mapping[str, str]) -> str | None:
    """The embed server's public address from --embed-base, else $RIHMA_EMBED_BASE; None when neither
    is set. A value that is not https://host[:port][/path] (or loopback http) is a ValueError."""
    return kembeds.embed_base(flag) or kembeds.embed_base(environ.get(kembeds.EMBED_BASE_ENV))


def embed_base_note(base: str | None) -> str:
    if base:
        return f"Embed snippets point at the embed server: {base}"
    return (f"Embed snippets point at the local embed server ({kembeds.LOCAL_EMBED_BASE}), for testing: set "
            f"--embed-base https://<your embed server> or {kembeds.EMBED_BASE_ENV} for websites.")


def gnomon_found() -> bool:
    """Whether ``kernel.model.gnomon_cmd()`` names a Gnomon that exists on this machine."""
    from kernel.models_setup import gnomon_found as found

    return found()


def chat_model() -> object:
    """Shape it in chat's model: the analyst, through Gnomon in the analyst lane, compiled again from the routing
    before each answer (kernel.models_setup.LaneModel). None when Gnomon is not found: the chat says so."""
    from kernel.models_setup import LaneModel

    return LaneModel(timeout=600) if gnomon_found() else None


def assistant_model_for(choice: str | None):
    """The assistant's model for ``--assistant``: 'gnomon' asks Gnomon in the analyst lane as the
    assistant role; 'map' answers from the cockpit map. By default Gnomon when it is found.
    Returns (model or None, a one-line note)."""
    if choice == "map":
        return None, "The assistant answers from the cockpit map (--assistant map)."
    if choice is None and not gnomon_found():
        return None, "The assistant answers from the cockpit map: Gnomon was not found (set GNOMON_CMD to use it)."
    from kernel.lanes import ensure_analyst_lane, load_routing
    from kernel.model import GnomonModel

    try:
        lane = ensure_analyst_lane(load_routing())
    except (OSError, ValueError, RuntimeError) as exc:
        return None, f"The assistant answers from the cockpit map: the analyst lane could not be prepared ({exc})."
    return GnomonModel(lane, timeout=180), f"The assistant asks Gnomon in the analyst lane ({lane})."


def public_origin_of(url: str) -> str:
    """The origin of a trusted HTTPS front, checked: https only (the sign-in link and the session token
    must never cross a network in clear), a host, and nothing after it."""
    parts = urlsplit(str(url).strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"--public-origin must be an https:// address with a host, not {url!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"--public-origin is an origin only (no path, query or fragment), not {url!r}")
    return f"https://{parts.netloc.lower()}"


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cockpit.server",
                                     description="The Rihma cockpit, on 127.0.0.1 only.")
    parser.add_argument("--home", help=f"the factory home (default: ${HOME_ENV} or var/)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on 127.0.0.1 (default {DEFAULT_PORT})")
    parser.add_argument("--host", default=LOOPBACK, help=f"must be {LOOPBACK}; any other address is refused")
    parser.add_argument("--quiet", action="store_true", help="do not log requests")
    parser.add_argument("--assistant", choices=("map", "gnomon"), default=None,
                        help="the assistant's model: gnomon (the default when Gnomon is found) or map")
    parser.add_argument("--embed-base", metavar="URL", default=None,
                        help="the embed server's public address that embed snippets point at "
                             f"(default ${kembeds.EMBED_BASE_ENV}; unset: the local embed server, for testing)")
    parser.add_argument("--public-origin", metavar="URL", default=None,
                        help="the https:// address of one trusted front (tailscale serve, a reverse proxy) that "
                             "forwards to this loopback cockpit; its Host and Origin are accepted")
    args = parser.parse_args(argv)
    try:
        public = public_origin_of(args.public_origin) if args.public_origin else None
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.host != LOOPBACK:
        print(f"refused: the cockpit binds to {LOOPBACK} only. From another machine use a tunnel: "
              f"ssh -L {args.port}:127.0.0.1:{args.port} <host>", file=sys.stderr)
        return 2
    try:
        embed_base = configured_embed_base(args.embed_base, os.environ)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    factory = Factory(args.home)
    model, note = assistant_model_for(args.assistant)
    try:
        server, bootstrap = make_server(factory, args.port, assistant_model=model, embed_base=embed_base)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"could not listen on {LOOPBACK}:{args.port}: {exc}", file=sys.stderr)
        return 1
    server.quiet = args.quiet
    server.shape_model = chat_model()
    # automations tick every minute while the cockpit runs (cockpit/automation_routes.py, FR-AUT1)
    server.automation_scheduler = Scheduler(factory, model=server.shape_model).start()
    server.public_origin = public
    print(f"Rihma cockpit for {factory.home}", flush=True)
    print(note, flush=True)
    print(embed_base_note(embed_base), flush=True)
    print(access_note(factory), flush=True)
    print(f"Open this link once to sign in: {public or server.origin}/#k={bootstrap}", flush=True)
    print(f"From another machine: ssh -L {server.port}:127.0.0.1:{server.port} <this host>, then open the link.",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
