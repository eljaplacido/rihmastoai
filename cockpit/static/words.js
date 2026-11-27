/* Words per persona (D-0024 point 5, FR-UXO1): the same meaning, said the way the reader works. A business
   owner, product owner, stakeholder, concept evaluator or end user reads plain words about outcomes; a
   developer, IT, operations or compliance person reads the precise technical term. Ids and data never change:
   only the words around them do.

     term(key, opts)           one concept from the GLOSSARY, as an element: the persona's word, with the other
                               word and a one-line explanation as its tooltip (data-term="<key>")
     tw(key, n)                the same word as plain text (plural when n is not 1)
     pick(plain, technical)    a sentence said two ways, chosen for the persona
     word(key)                 a named piece of interface text for the persona (falls back to the plain text)
     meaning(kind, verdict)    what choosing a verdict on a card does, in one line
     emptyLine(view)           what would appear in an empty view; emptyHow(view) how it gets there;
                               emptyState(view) draws both

   One word per concept: every view says "decision record" (or "ledger") through the glossary, never a third
   word. Wording a person flags as unclear is changed here, in one place, and reviewed like any change. */

import { S, h, icon, wordHooks, FACTORY_PID } from "./core.js";

const TECH = new Set(["developer", "it", "operations", "compliance", "ai_architect"]);
export function technical() { return TECH.has(S.persona); }
const COMPLIANCE = new Set(["compliance"]);

/* The glossary: [business word, technical word, what it means]. The explanation is shown as the term's tooltip
   to both readers, so a business owner who meets "ledger" in a log line, or a developer reading a business
   summary, can match the two words. Plurals add "s" unless a fourth and fifth entry give them. */
export const GLOSSARY = {
  ledger: ["decision record", "ledger", "The signed, append-only record of every decision and event in the project. Nothing in it is ever edited."],
  canon: ["project record", "canon", "Everything the project knows: its request, questions, requirements, tasks and decisions."],
  spec: ["requirements", "spec", "What will be built, written from the answered questions: the requirements and the checks each must pass.", "requirements", "specs"],
  contract: ["agreed checks", "contract", "The requirements turned into checks the work must pass before it counts as done.", "agreed checks", "contracts"],
  criterion: ["acceptance check", "acceptance criterion", "One testable condition a requirement must meet.", "acceptance checks", "acceptance criteria"],
  gate: ["quality check", "gate", "The automatic review every piece of work passes before it is accepted: the tests run and an independent AI reviewer judges it."],
  round: ["attempt", "round", "One try at a task: the AI builds it, then the quality check reviews it."],
  cell: ["AI build team", "cell", "The AI that builds one task: a builder writes the work and a separate reviewer checks it."],
  merged: ["accepted", "merged", "The work passed its quality check and is part of the product.", "accepted", "merged"],
  holdout: ["hidden test", "holdout scenario", "A test the AI builders never see, kept back to check the finished product honestly."],
  fail_first: ["test that fails before the fix", "fail-first test", "A test written before the work that must fail first, so it is known to test the right thing."],
  escalation: ["stuck task", "escalation", "A task whose quality check kept failing: a person decides whether to retry, accept or stop it."],
  evidence_pack: ["proof package", "evidence pack", "One file with the proof for every acceptance check, for an auditor or customer."],
  capability_pack: ["release package", "capability pack", "What a release is: its version, what built and checked it, and fingerprints that show it is unchanged."],
  attestation: ["signed proof", "attestation", "A signed statement of how the release was built and checked."],
  provenance: ["where it came from", "provenance", "The source behind a statement: which question, document or person it rests on.", "where they came from", "provenance"],
  autonomy: ["AI independence", "autonomy cap", "How much the AI may do on its own before a person must decide."],
  posture: ["working rules", "posture", "The rules this project runs under, such as how carefully it is checked and who must approve."],
  maturity: ["ambition", "maturity", "How far the project is meant to go: a quick try-out, a demo or a product people depend on."],
  mode: ["who answers", "mode", "Who answers the project's questions: people, the AI as assumptions to confirm later, or both."],
  signal: ["incoming need", "signal", "A need that arrived from a person, a chat, a website or a monitoring alert, waiting to be sorted."],
  triage: ["sorting", "triage", "Deciding where an incoming need goes: to an existing project, a new idea, or nowhere."],
  stale: ["out of date", "stale", "An approval given before something it depends on changed: it should be looked at again.", "out of date", "stale"],
  sbom: ["parts list", "SBOM", "The list of every software component the product is made of."],
  hash: ["fingerprint", "hash", "A short code computed from a file: if the file changes by one letter, the code changes."],
  commit: ["saved version", "commit", "One saved change in the code's history."],
  repository: ["code", "repository", "Where the project's code and its history are kept.", "code", "repositories"],
  mcp: ["AI tool connection", "MCP", "The standard way an AI coding tool connects to Rihmasto and reads what it needs."],
  verdict: ["decision", "verdict", "What a person or the quality check decided."],
  judge: ["independent reviewer", "judge", "A separate AI that checks the builder's work and never builds it itself."],
  runner: ["where the AI works", "cell runner", "The place the AI build team runs: this machine, a container or another computer."],
  ci: ["automatic checks", "CI", "Checks that run by themselves on every change to the code.", "automatic checks", "CI"],
  stage: ["step", "stage", "One of the seven steps from a need to a product in use."],
  canary: ["trial with a few users", "canary", "A release shown to a few users first, before everyone gets it."],
  paved_road: ["standard setup", "paved road", "A ready, approved way to set up hosting, data or a pipeline, so each project need not invent its own."],
  persona: ["role", "persona", "The role you act in: business owner, developer, compliance and so on. It decides which cards are yours."],
  assumption: ["assumption", "assumption", "An answer the AI took for granted, to be confirmed by a person by its due date."],
  requirement: ["requirement", "requirement", "One thing the product must do, written from the answered questions."],
  release: ["release", "release", "A version of the product that passed its checks and can be tried or put into use."],
  incident: ["problem in use", "incident", "Something went wrong where the product runs."],
  deploy_gate: ["go-live approval", "deploy gate", "The approval a person gives before a release is put into use."],
  console: ["command window", "console", "Where commands run in the project's own folder, with every run recorded."],
  job: ["background run", "job", "Work the factory does in the background, such as advancing a project."],
  card: ["decision", "card", "Something waiting for a person to decide: a question, an approval, a change or a release to try."],
  scenario: ["test case", "scenario", "A described situation the product must handle."],
  harness: ["coding agent", "harness", "An AI coding tool you already use (Claude Code, Codex or OpenCode) that does Rihmasto's text work."],
  apparatus: ["setup", "apparatus", "The tools a cell needs to run: the builder, the reviewer, the tests."],
  // Agent operations (agentops.js, FR-AOP1)
  token: ["token", "token", "The unit an AI model counts text in, about three quarters of a word: AI usage and its price are counted in tokens."],
  latency: ["response time", "latency", "How long an AI agent, or a tool it called, took to answer."],
  context_drift: ["out-of-date briefing", "context drift", "An AI agent last worked before records it was not given were written: what it knew is behind the project."],
  overhead: ["fixed cost per call", "harness overhead", "What the coding agent's own setup adds to every call (its standing instructions), before the work's own context."],
  prompt_cache: ["reuse of repeated text", "prompt cache", "Text sent the same way at the start of every call can be reused by the AI provider at a lower price."],
};
function cap1(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
/* A glossary word as plain text: n !== 1 gives the plural; opts.cap capitalises it. */
export function tw(key, n, opts) {
  const g = GLOSSARY[key];
  if (!g) return key;
  const tech = technical();
  const many = n !== undefined && n !== 1;
  let w = many ? (tech ? g[4] : g[3]) || (tech ? g[1] : g[0]) + "s" : tech ? g[1] : g[0];
  if (opts && opts.cap) w = cap1(w);
  return w;
}
/* A glossary word as an element: the persona's word, with the explanation (and the other reader's word) as its
   tooltip. A term is explained wherever it appears; the wording test treats it so. */
export function term(key, opts) {
  const o = opts || {};
  const g = GLOSSARY[key];
  if (!g) return String(key);
  const tech = technical();
  const other = tech ? g[0] : g[1];
  const tip = g[2] + (other && other !== (tech ? g[1] : g[0]) ? " (" + (tech ? "in plain words: " : "technical term: ") + other + ")" : "");
  return h("span", { class: "term", "data-term": key, tip, tabindex: o.focus ? "0" : null }, tw(key, o.n, o));
}
export function explain(key) { const g = GLOSSARY[key]; return g ? g[2] : ""; }

/* A sentence said for each reader: the plain one for business personas, the precise one for technical ones. */
export function pick(plain, tech) { return technical() ? (tech === undefined ? plain : tech) : plain; }

/* A record's own text (a title, a brief, a finding, a log line): shown as written, never reworded. */
export function datum(text, tag) { return h(tag || "span", { "data-ud": "" }, text); }

// The seven stages: [plain, technical] (the technical name is the kernel's own).
const STAGE_WORDS = {
  1: ["Need and decision", "Need and decision"], 2: ["Concept and questions", "Concept"],
  3: ["Requirements", "Technical translation"], 4: ["Design and checks", "Spec and architecture"],
  5: ["Build and check", "Build and verify"], 6: ["People try it", "User validation"], 7: ["Live and measured", "Deploy and measure"],
};
export function stageWord(n, fallback) { const w = STAGE_WORDS[n]; return w ? (technical() ? w[1] : w[0]) : fallback || ""; }
// The four bands of stages.
const BAND_WORDS = { Decide: "Decide", Shape: "Shape", Deliver: "Deliver", Run: "Run" };
export function bandWord(b) { return BAND_WORDS[b] || b; }
// Who answers the project's questions (its mode): [plain, technical].
const MODE_WORDS = { socratic: ["people answer", "socratic"], assume: ["the AI assumes, people confirm", "assume"],
  mixed: ["people and the AI", "mixed"] };
export function modeWord(m) { const w = MODE_WORDS[m]; return w ? (technical() ? w[1] : w[0]) : m; }
// What a task's status is called: [plain, technical].
const STATUS_WORDS = { pending: ["Not started", "Pending"], building: ["Being built", "Building"], merged: ["Done", "Merged"],
  done: ["Marked done by a person", "Marked done"],   // a person's done, its own lane (FR-LND2)
  escalated: ["Stuck: needs you", "Escalated"], stopped: ["Stopped", "Stopped"], open: ["Open", "Open"] };
export function statusWord(s) { const w = STATUS_WORDS[s]; return w ? (technical() ? w[1] : w[0]) : s; }
// The kernel as an actor: a deterministic rule.
export function kernelWord() { return technical() ? "the kernel" : "an automatic rule"; }
wordHooks.kernel = kernelWord;
// A card's kind for a business reader; a technical reader keeps the kernel's own name (core.js KIND_LABEL).
const KIND_PLAIN = { escalation: "Stuck task", deploy_gate: "Go-live approval", road: "Standard setup", holdout_ruling: "Hidden test result",
  runner: "Where the AI works", go_ahead: "Look before building", trust: "Trust", change: "Change request", concept: "New idea",
  update: "Upgrade offer", question: "Question", approval: "Approval", validation: "Release to try", incident: "Problem in use",
  enforcement: "Check before it goes on", structure: "Rihmasto's own way", ask: "Asked of a person" };
export function kindWord(kind) { return technical() ? null : KIND_PLAIN[kind] || null; }
wordHooks.kind = kindWord;
// A verdict whose risk the button must say: accepting work that failed its checks.
const VERDICT_PLAIN = { accept_as_is: "Accept although checks failed" };
wordHooks.verdict = (v) => (technical() ? null : VERDICT_PLAIN[v] || null);

// [plain, technical, compliance (optional)]
const WORDS = {
  "capsule.now": ["What waits on you and where the project stands", "Open decisions, review and status", "Open decisions and status"],
  "capsule.build": ["What is being made: the requirements, the work and the changes", "Spec, contract, tasks, changes, alignment and the console"],
  "capsule.run": ["What is delivered and how it runs", "Releases, outputs, health checks and automations"],
  "capsule.govern": ["The proof: evidence, decisions and whether it is on track", "Evidence per criterion, track, insights and the ledger",
    "Evidence, the decision record, insights and staying on track"],
  "capsule.agents": ["The AI agents working on it and what they were told", "Agent channel, sessions, AI tools and context"],
  "scope.all": ["All projects", "All projects"],
  "inbox.lede": ["Each card asks you one thing. Pick an answer; add why if you like.",
    "Open cards your persona may decide. Pick a verdict, optionally give a reason; it is signed and recorded."],
  "inbox.empty": ["Nothing waits on you here. When a decision is yours, a card appears here with the choices.",
    "No open card for this persona. Cards open on questions, approvals, escalations, gates and incidents."],
  "details": ["Details", "Details (ids, refs, payload)"],
  "square.lede": ["How needs move from arriving to production, across all projects",
    "Signal intake, concept validation, build pipeline, end-user testing and production, per project or all"],
  // view labels (the capsule rows and each view's heading)
  "view.spec": ["Requirements", "Spec & contract"],
  "view.enforcement": ["How strict each stage is", "Enforcement"],
  "view.ledger": ["Decision record", "Ledger"],
  "view.cell": ["AI build team", "Cell"],
  "view.checks": ["Health", "Health"],
  "view.align": ["Code and plan match", "Alignment"],
  "view.console": ["Command window", "Console"],
  "view.assessment": ["Code assessment", "Assessment"],
  "view.track": ["On track?", "Track"],
  // each view's question under its heading
  "q.overview": ["Where is this project, and what waits on you?", "Stage, open cards, health and the next step"],
  "q.inbox": ["What do you need to decide?", "Open cards this persona may decide"],
  "q.questions": ["What does the project still need to know?", "Open questions from the intake panel, by perspective"],
  "q.assumptions": ["What did the AI take for granted, and when must someone confirm it?", "Assumptions with their due dates and settlement"],
  "q.spec": ["What will be built, and how will we know it works?", "Requirements, acceptance criteria and the compiled contract"],
  "q.tasks": ["What work is planned and how far along is each piece?", "Tasks with their status, rounds and last gate verdict"],
  "q.changes": ["What changes were asked for, and what did each touch?", "Change cards with their impact and decision"],
  "q.releases": ["What has been delivered?", "Releases with their capability pack, hashes and signature"],
  "q.evidence": ["What proves each requirement is met?", "Evidence per acceptance criterion: verified, claimed or missing"],
  "q.ledger": ["Who decided what, and when?", "The hash-chained ledger: decisions and events"],
  "q.cell": ["How did the AI build team do on each task?", "Gnomon cell runs: rounds, gate verdicts and models"],
  "q.try": ["Try the latest release and say how it works for you", "End-user validation of the latest release"],
  "q.plan": ["What will be built? Look it over and approve it.", "The plan for approval: requirements, criteria and integrations"],
  // a compact box opened for review (expand.js, FR-CMP1)
  "expand.open": ["Expand", "Expand"],
  "expand.close": ["Collapse", "Collapse"],
  "expand.open_tip": ["Show everything in this box; its size stays as you set it", "Show the full content; the layout's size is unchanged"],
  "expand.close_tip": ["Fold it back to the size you set", "Back to the compact size"],
  "expand.kept": ["Shown in full for review. On the page it keeps the size you set.", "Full content for review; the layout keeps the size you set."],
  "expand.failed": ["This box could not be shown in full:", "The full content could not be drawn:"],
  "expand.chat_open": ["“{name}” is open in full here. Collapse folds it back; its size stays as you set it.",
    "Expanded “{name}” on this view. Collapse folds it back; the layout's size is unchanged."],
  "expand.chat_close": ["“{name}” is folded back to the size you set.", "Collapsed “{name}” back to its compact size."],
  "expand.last_action": ["Last action", "Last action"],
  "expand.recent": ["The steps before it, newest first", "Earlier tool steps, newest first"],
  // the agent channel's head: what it is for and what to expect (agents.js, FR-CHN2)
  "q.agents": ["Where the AI coding agents working on this project and Rihma talk about it. Ask here: Rihma answers from the project's records and can put your question to a connected coding agent.",
    "Coding agents (Claude Code, Cursor, Codex, any MCP client) and Rihma's agents talk here about this project. A person asks; Rihma answers from the records and can put the question to a connected coding agent."],
  "channel.expect.ask": ["Ask anything about the project: Rihma answers here at once, with the next steps as buttons and a Trace of what it rests on.",
    "Ask anything: Rihma answers by rule from the records (or through its model), with next steps as buttons and a Trace."],
  "channel.expect.agent": ["Write “ask Claude Code …” (or Cursor, Codex, the agent): Rihma passes your question to that agent, and its answer comes back here.",
    "“ask Claude Code …” (or Cursor, Codex, the agent): Rihma posts the question to that agent; it reads it over MCP (rihma_channel_read) or at its next session start, and answers here."],
  "channel.expect.agents": ["Agents post what they did, their questions and suggested answers here; a suggested answer counts only when you confirm it.",
    "Agents post progress, questions, gate results and proposals; a proposal answers nothing until a person confirms it."],
  "channel.none": ["No coding agent is connected to this project yet.", "No coding agent has posted here yet: none is connected."],
  "channel.ask": ["Ask a coding agent", "Ask a coding agent"],
};
export function word(key, fallback) {
  const w = WORDS[key];
  if (!w) return fallback === undefined ? key : fallback;
  if (COMPLIANCE.has(S.persona) && w[2]) return w[2];
  return technical() ? w[1] : w[0];
}
/* A view's label for this reader (Ledger or Decision record), or the given fallback. */
export function viewWord(id, fallback) { return WORDS["view." + id] ? word("view." + id) : fallback; }

// What choosing a verdict does: [plain, technical].
const MEANING = {
  "escalation.retry": ["Let Rihma try again, with what the checks said", "Run another cell round with the objections as input"],
  "escalation.accept_as_is": ["Take the work as it is, although the checks did not pass", "Merge the judged head despite the failing gate (recorded as accepted as is)"],
  "escalation.stop": ["Stop work on this task", "Stop the task: no more rounds"],
  "change.accept": ["Do it: the parts it touches are redone", "Accept: reopens the tasks and stales the approvals listed under Details"],
  "change.reject": ["Do not do it", "Reject: the change is closed"],
  "change.defer": ["Not now: keep it for later", "Defer: it stays parked as decided-deferred"],
  "approval.approve": ["Yes, go ahead", "Approve: the next stage may start"],
  "approval.reject": ["No: send it back, and say why", "Reject: it is redrawn from your reason"],
  "validation.accept": ["It works: accept the release", "Accept the release"],
  "validation.fix": ["Something is broken: ask for a fix", "File a defect against the release"],
  "validation.change": ["It works, but should be different: ask for a change", "File a change request"],
  "validation.keep": ["Keep it as it is for now", "Keep the release; no follow-up"],
  "deploy_gate.approve": ["Let it go live", "Approve the deploy gate"],
  "deploy_gate.refuse": ["Do not let it go live yet", "Refuse the deploy gate"],
  "enforcement.approve": ["Let it go on (recorded with your name)", "Approve: an override, recorded"],
  "enforcement.refuse": ["Keep it held", "Refuse: keep it held"],
  "structure.will_fix": ["We will bring these into line", "Will fix: the card stays answered while these stay the same"],
  "structure.advise": ["Only suggest this from now on", "Advise instead: the convention becomes a suggestion for this project"],
  "incident.acknowledge": ["I know about it and it is being handled", "Acknowledge the incident"],
  "incident.rollback": ["Go back to the version before", "Roll back to the previous release"],
  "incident.open_defect": ["Have it fixed as a defect", "Open a defect change card"],
  "road.configured": ["It is set up", "The paved road is configured"],
  "road.declined": ["We will not set this up", "Decline the infrastructure change"],
  "trust.granted": ["Trust it", "Grant the trust"],
  "trust.declined": ["Do not trust it", "Decline the trust"],
  "runner.approve": ["Use this runner", "Approve the runner; its version is pinned"],
  "runner.decline": ["Do not use it", "Decline the runner"],
  "holdout_ruling.product_defect": ["The product is wrong: fix the product", "Product defect: a change against the product"],
  "holdout_ruling.scenario_defect": ["The test is wrong: fix the test", "Scenario defect: the holdout scenario is revised"],
  "concept.validate": ["Make it a project", "Validate: a project is created"],
  "concept.park": ["Not now: park it, and say why", "Park the concept (reason required)"],
  "concept.reject": ["Do not do it, and say why", "Reject the concept (reason required)"],
  "update.trial": ["Try it", "Start a trial"],
  "update.decline": ["Do not take it", "Decline the update"],
  "update.defer": ["Later", "Defer the update"],
  "connector.enable": ["Turn it on", "Enable the connector"],
  "connector.decline": ["Leave it off", "Decline the connector"],
  "go_ahead.go": ["Build it: I have looked", "Go: start the build"],
  "go_ahead.skip": ["Build it without my look", "Skip the look-ahead and build"],
  "question.answer": ["Give your answer", "Answer the question"],
  "question.assume": ["Let Rihma assume, to be confirmed later", "Record the proposal as an assumption with a due date"],
};
export function meaning(kind, verdict) {
  const m = MEANING[kind + "." + verdict];
  if (!m) return "";
  return technical() ? m[1] : m[0];
}

/* Every view's empty state: what would appear, and how it gets there, for each reader.
   { view: [[plain what, plain how], [technical what, technical how]] } */
const EMPTY = {
  inbox: [["Nothing waits on you here.", "A card appears here when a decision is yours: a question, an approval, a release to try."],
    ["No open card for this persona.", "Cards open on questions, approvals, escalations, deploy gates and incidents."]],
  questions: [["No questions yet.", "Questions appear here once the project starts: press Advance on the Overview and the AI asks what it needs to know."],
    ["No open questions.", "The intake panel asks them at stage 2; Advance on the Overview runs it."]],
  assumptions: [["Nothing has been assumed.", "When the AI answers a question itself, the answer appears here with the date by which a person should confirm it."],
    ["No assumptions.", "An assumption is recorded when a question is answered in assume or mixed mode, with a due date to settle it."]],
  spec: [["The requirements are not written yet.", "They appear here once the project's questions are answered: press Advance on the Overview."],
    ["No spec yet.", "The spec is written at stage 3 once the blocking questions are answered; the contract is compiled at stage 4."]],
  plan: [["No plan yet.", "The plan of what will be built appears here for your approval once the questions are answered."],
    ["No plan yet.", "The plan is drawn at stage 3, once the questions that block it are answered."]],
  tasks: [["No work planned yet.", "The pieces of work appear here once the plan is approved."],
    ["No tasks yet.", "Tasks come from the compiled contract (stage 4): approve the plan, then Advance."]],
  cell: [["The AI build team has not worked on this project yet.", "Each attempt at a task appears here once the work starts."],
    ["No Gnomon runs recorded.", "A run appears here once a cell has run a task through Gnomon (stage 5)."]],
  releases: [["Nothing delivered yet.", "A release appears here when all the work has passed its quality checks."],
    ["No release yet.", "A release is cut when every task merges through the gate (stage 5 to 7)."]],
  try: [["Nothing to try yet.", "When a release is ready, it appears here for you to try and say how it works."],
    ["No release to validate.", "A validation card opens for end users once a release is cut (stage 6)."]],
  changes: [["No change asked for.", "Ask for one with Change in the project's header; it appears here with what it would touch."],
    ["No change cards.", "File one with Change in the header or `rihmasto change`; each lists its impact."]],
  ledger: [["No decisions recorded yet.", "Every decision and event is written here as it happens, signed with who made it."],
    ["No ledger records.", "Each write appends a hash-chained record here."]],
  evidence: [["No proof yet.", "Proof for each acceptance check appears here once the work has been built and checked."],
    ["No evidence yet.", "Evidence per criterion is recorded when tasks merge through the gate."]],
  outputs: [["Nothing set up to deliver yet.", "Choose where the results go (a folder, a shared drive or a code host) and they appear here."],
    ["No outputs configured.", "Configure an output target; each build appears here with its revision."]],
  automations: [["No automation yet.", "Start from a template, ask Rihma, or press New automation; each scheduled or triggered task appears here."],
    ["No automation yet.", "Start from a template or create one with New automation or `rihmasto automation`; runs appear here."]],
  checks: [["No health checks yet.", "Checks that watch the product (tests, security scans, uptime) appear here once they are set up or suggested."],
    ["No checks configured.", "Add a check or accept a suggested one; results appear here with their last run."]],
  console: [["No commands run yet.", "Commands you or an agent run in the project's folder appear here, each one recorded."],
    ["No console runs.", "Runs appear here, each recorded in the ledger with its exit code."]],
  track: [["Nothing to track yet.", "Progress against the plan appears here once tasks exist."],
    ["No track data.", "Tracking starts once the contract is compiled and tasks exist."]],
  insights: [["Not enough work done for insights yet.", "Patterns in how the work goes (time, cost, retries) appear here as tasks are built."],
    ["No insight data yet.", "Insights are computed from rounds, gates and costs as tasks run."]],
  review: [["Nothing new since you last looked.", "Decisions, finished work and changes appear here as they happen."],
    ["No changes since your last look.", "New ledger records, merges and card decisions appear here."]],
  agents: [["No agent has worked on this yet.", "Hand the work to an AI coding agent from the header; what it does and says appears here."],
    ["No agent sessions.", "Hand off from the header or connect an agent over MCP; its messages and actions appear here."]],
  aitools: [["No AI tool setup found in this code.", "Instructions for AI coding tools (such as CLAUDE.md or AGENTS.md) appear here once they are in the code."],
    ["No AI tool configuration found.", "CLAUDE.md, AGENTS.md, Cursor rules, skills, hooks and MCP servers appear here once committed."]],
  align: [["Not compared yet.", "Rihmasto compares the code with the plan and lists where they differ here."],
    ["Not aligned yet.", "Run the alignment to map the repository against the contract; findings appear here."]],
  assessment: [["Not assessed yet.", "An assessment of the code (its structure, tests and risks) appears here once it is run."],
    ["Not assessed yet.", "Run the assessment; its findings per area appear here."]],
  agentops: [["No AI agent has worked here in this period.", "What each AI helper costs, how fast it answers and what it is given appear here as soon as one works on the project (asking questions, writing the requirements, building or checking)."],
    ["No agent run recorded in the window.", "Runs appear per role, harness and model once an agent runs (intake, spec, a builder cell, a gate, Ask Rihma or a coding agent), each with its tokens, cost and seconds."]],
  agentops_all: [["No AI agent has worked in this period.", "Each AI helper's cost, speed and briefing appear here across all projects once one works on any of them."],
    ["No agent run recorded in the window across the projects.", "Every project's runs (and Rihmasto's own) appear per role, harness and model once an agent runs."]],
  agentops_prices: [["No AI model to price yet.", "Each AI model your helpers use appears here once one works, with what it costs per million tokens; you can price a model before that too."],
    ["No model in the runs or the price table.", "Every model the runs name appears here with its price per million tokens in and out; price one before it runs with the form below."]],
  // observer links (share.js, observer.js, FR-SHR1)
  share: [["You are not sharing anything.", "Make an observer link above: a colleague then watches your work, read only, for an hour, a day or a week. You pass the link on yourself."],
    ["No observer link.", "Make one above (scope, duration, guest); only its hash is kept, it is shown once and revoked at once."]],
  share_comments: [["No comment from a guest yet.", "What a guest writes on the page you shared appears here, signed with their name."],
    ["No guest comment.", "Comments posted through /o/ appear here, marked as a guest's, each recorded in the ledger."]],
  share_suggestions: [["No suggested answer waits.", "On a link for defining a project together, a guest's suggested answers to the intake questions wait here for you to confirm or decline."],
    ["No guest suggestion waiting.", "Suggestions from a link with intake allowed wait here; Confirm answers the question signed by you."]],
  observer: [["Nothing shared here yet.", "The person who shared this link has nothing in this view yet. It updates by itself as they work."],
    ["Empty in scope.", "The view updates every few seconds while the link is active."]],
  observer_channel: [["No message in the agent channel yet.", "Messages between people and AI agents on this project appear here as they are posted."],
    ["No channel message.", "Posts to the project's agent channel appear here, masked."]],
  observer_comments: [["You have not commented yet.", "Write below: your comment is signed with your name, marked as a guest's, and the person who shared this sees it."],
    ["No comment from this link.", "Comments are signed as the guest and recorded in the ledger."]],
  jobs: [["Nothing running in the background.", "When you press Advance or start a run, it appears here while it works."],
    ["No jobs in this session.", "Jobs started from the cockpit (Advance, builds, runs) appear here with their logs."]],
  // a precise assessment (cockpit/static/assessment_precise.js, FR-ASP1)
  assess_plans: [["No plan was taken from the team's documents.", "When the team's own plans and task lists are brought in (Alignment), each shows here with the date it was last changed, so an old plan is flagged before you take it."],
    ["No requirement or task imported from a document.", "Read the repository in Alignment; each imported requirement and task shows here with its document's last commit date, and one older than the code is flagged before it is accepted."]],
  assess_runner: [["Rihmasto does not see this project's own test results yet.", "Tell it the command the team runs its tests with and where the results are saved; the next assessment reads them."],
    ["Not measured by Rihmasto yet: map its runner.", "Name the command the project runs its own tests with and the results file it writes (JUnit XML or JSON counts); Rihmasto reads it at the assessed revision and never runs it."]],
  // A clear landing and tasks you open (starthere.js, tasklive.js, runlog.js; FR-LND1)
  start_here: [["Nothing waits on you here now.", "When a decision, a question or a check needs you, it shows here as the next thing to do."],
    ["No step waits on you.", "A step appears here when a card, a question, an unmapped source or a finding needs a person."]],
  task_criteria: [["No acceptance checks name this task yet.", "They appear when its requirement gets its checks, from the plan or from the repository's own spec."],
    ["No criteria on this task.", "Criteria come with its requirement in the contract; accept the repository's own in Alignment."]],
  task_tests: [["No test checks this yet.", "Tests appear when one names its acceptance checks, or when the repository's tests are traced to them in Alignment."],
    ["No test names its criteria.", "A test that carries a criterion id, a gate round, or a test traced in Alignment shows here with its last result."]],
  task_commits: [["No change to the code names this task yet.", "A commit whose message carries the task's id shows here."],
    ["No commit carries this task's id.", "Commits that name the task id in their message show here, read from the project's repository."]],
  task_agents: [["No AI helper has worked on this task yet.", "Hand it to a coding agent and its work shows here."],
    ["No agent or session touched this task.", "Hand-offs, channel posts and coding-agent sessions that name the task show here."]],
  task_history: [["Nothing has happened to this task yet.", "Each start, check and decision on it is listed here as it happens."],
    ["No ledger record names this task.", "Cell runs, gate rounds, merges, starts and marks on it are listed here."]],
  tasks_filtered: [["The filters hide every task here.", "Show every task, or choose another status or source above."],
    ["No task matches this project's filters.", "Clear them with Show every task; each project keeps its own filters."]],
  task_missing: [["This task is not in the project.", "Open Tasks to see the project's work."],
    ["No such task in the contract.", "Open Tasks for the contract's tasks."]],
  run_changed: [["The run changed nothing in the project's records.", "What a run adds (tasks, decisions, checks) is listed here when it ends."],
    ["No ledger record was added while it ran.", "Tasks, cards, gates, merges and releases recorded during the run are listed here."]],
  runs: [["Nothing has run in this session yet.", "Runs you start (Advance, an adoption, a check) and the AI build team's work appear here, each with its whole log."],
    ["No job or running cell.", "Jobs started from the cockpit and cells holding a lane appear here, each with its whole log."]],
};
export function emptyLine(view, fallback) {
  const e = EMPTY[view];
  if (!e) return fallback || "";
  const [what, how] = technical() ? e[1] : e[0];
  return what + " " + how;
}
export function emptyWhat(view) { const e = EMPTY[view]; return e ? (technical() ? e[1] : e[0])[0] : ""; }
export function emptyHow(view) { const e = EMPTY[view]; return e ? (technical() ? e[1] : e[0])[1] : ""; }
/* An empty view: what would appear (bold) and how it gets there, with an optional action. */
export function emptyState(view, action, opts) {
  const o = opts || {};
  return h("div", { class: "empty teach", "data-empty": view },
    o.icon ? h("span", { class: "empty-ic" }, icon(o.icon)) : null,
    h("p", { class: "empty-t" }, o.what || emptyWhat(view)),
    h("p", { class: "empty-how" }, o.how || emptyHow(view)), action || null);
}

/* -- the shell, the kernel's own lines and the figures, in the reader's words (the two readers' review) --------

   A business owner and a developer read every page and flagged what said nothing to them. The fixes live here,
   so one place says each thing; the kernel's records keep their own wording (Details shows it). */

// The pages in the sidebar, the bottom bar and the search: [plain, technical]. The technical name is the page's
// own (Ask Rihma and the docs call it so); its tooltip gives the other.
const PAGE_WORDS = { square: ["Flow of work", "Square"], floor: ["AI build quality", "Floor"],
  catalogue: ["What we have built", "Catalogue"], jobs: ["Running now", "Jobs"] };
export function pageWord(id) { const w = PAGE_WORDS[id]; return w ? (technical() ? w[1] : w[0]) : null; }
wordHooks.page = pageWord;

// The same idea under one name everywhere: the factory's own bucket of proposals tied to no project.
export function factoryWord() { return "Rihmasto itself"; }
/* A project's title, with the factory's own project under its one name on every face ("Rihma itself", "The factory
   itself" and "New ideas (no project yet)" before). */
export function titleOf(pid, title) {
  return pid === FACTORY_PID || title === "Rihma itself" || title === "The factory itself" || title === "Rihmasto itself" ? factoryWord() : title || pid || "";
}

/* A kernel line's "(s)" plurals said properly: "1 decision(s)" → "1 decision", "3 round(s)" → "3 rounds". */
export function plurals(text) {
  return String(text == null ? "" : text).replace(/\b(\d+) ([a-z][a-z -]*?)\(s\)/gi, (m, n, w) => n + " " + (n === "1" ? w : w + "s"));
}

// A card kind as a plain noun, for counting ("2 questions"): [one, many].
const KIND_NOUN = { escalation: ["stuck task", "stuck tasks"], question: ["question", "questions"],
  change: ["change request", "change requests"], concept: ["new idea", "new ideas"], update: ["upgrade offer", "upgrade offers"],
  approval: ["approval", "approvals"], validation: ["release to try", "releases to try"],
  deploy_gate: ["go-live approval", "go-live approvals"], incident: ["problem in use", "problems in use"],
  holdout_ruling: ["hidden test result", "hidden test results"], go_ahead: ["look before building", "looks before building"],
  road: ["setup request", "setup requests"], trust: ["trust request", "trust requests"], runner: ["tool to approve", "tools to approve"] };
function kindNoun(k, n) { const w = KIND_NOUN[String(k).replace(/ /g, "_")]; return w ? (n === 1 ? w[0] : w[1]) : String(k); }

/* Where a card or signal came from, when the kernel wrote it into the title as "[embed E-001] ..." or
   "[signal S-001 via chat] ...": the request itself, and its source as a small tag. */
const SOURCE_WORDS = { embed: "From the website chat", chat: "From a chat", manual: "Typed in by a person", email: "From an email",
  monitoring: "From monitoring", meeting: "From a meeting", feed: "From a feed", api: "From another system" };
export function cardTitle(title) {
  const t = String(title == null ? "" : title);
  const m = /^\[(embed|signal) ([A-Z]+-\d+)(?: via ([\w-]+))?\]\s*/.exec(t);
  let text = m ? t.slice(m[0].length) : t;
  const from = m ? (m[1] === "embed" ? SOURCE_WORDS.embed : SOURCE_WORDS[m[3]] || "From " + (m[3] || "a request")) : null;
  const esc = /^(T-\d+) did not pass its gate after (\d+) round\(s\)$/.exec(text);
  if (esc) {
    const n = Number(esc[2]);
    text = pick("Task " + esc[1] + " failed its quality check " + (n === 1 ? "once" : n + " times"),
      esc[1] + " failed its gate in " + n + (n === 1 ? " round" : " rounds"));
  }
  text = text.replace(/^Validate as a concept\?\s*/, pick("New idea: ", "Concept: "));
  return { text: plurals(text), from, ref: m ? m[2] : null };
}
/* A card title as an element: the request as written (data-ud), and where it came from as a tag. */
export function cardTitleEl(title, tag) {
  const c = cardTitle(title);
  return [h(tag || "span", { "data-ud": "" }, c.text), c.from ? h("span", { class: "chip neutral src-tag", tip: c.ref || null }, c.from) : null];
}

/* A project's "now" line from the kernel (kernel/status.py), in the reader's words: what waits, and on whom. */
export function nowSaid(line) {
  const t = String(line == null ? "" : line);
  const w = /^(\d+) decision\(s\) waiting: ([^;]+)(;.*)?$/.exec(t);
  if (w) {
    const n = Number(w[1]);
    const kinds = w[2].split(",").map((k) => k.trim()).filter(Boolean);
    const rest = w[3] ? " " + w[3].slice(1).trim() : "";
    if (technical()) return plurals(t);
    if (kinds.length === 1) return n + " " + kindNoun(kinds[0], n) + (n === 1 ? " needs" : " need")
      + (kinds[0] === "question" ? " an answer." : " a decision.") + rest;
    return n + " decisions wait: " + kinds.map((k) => kindNoun(k, 2)).join(", ") + "." + rest;
  }
  const r = /^Stage (\d): ready for the next step\.$/.exec(t);
  if (r) {
    const s = Number(r[1]);
    if (technical()) return "Stage " + s + " (" + stageWord(s) + ") done. Advance runs stage " + Math.min(7, s + 1) + ".";
    if (s === 5) return "Built and checked. Next: people try it. Press Advance to continue.";
    if (s >= 7) return "Live. Changes and feedback come back as new requests.";
    return "Step " + s + " (" + stageWord(s).toLowerCase() + ") is done. Next: " + stageWord(s + 1).toLowerCase() + ". Press Advance to continue.";
  }
  return plurals(t);
}

/* An activity or decision-record line ("analyst change triaged", "T-002 round 2: gate failed") as a sentence. */
const EVENT_WORDS = {
  task_started: ["started a task", "started a task"], task_marked_done: ["marked a task done, with evidence", "marked a task done"],   // FR-LND1
  start_here_hidden: ["hid Start here", "hid Start here"], start_here_shown: ["showed Start here again", "showed Start here"],
  change_triaged: ["sorted a change request", "triaged a change"], contract_compiled: ["fixed the build plan", "compiled the contract"],
  intake_done: ["finished the first questions", "finished the intake"], card_opened: ["asked for a decision", "opened a card"],
  evidence_exported: ["downloaded the proof package", "exported the evidence pack"], pack_versioned: ["updated the release package", "versioned the capability pack"],
  release_reached_test: ["made a release ready for testing", "release reached test"], answer: ["answered a question", "answered"],
  decision: ["decided", "decided"], merged: ["accepted a task", "merged a task"], spec_written: ["wrote the requirements", "wrote the spec"],
};
export function eventWord(kind) { const w = EVENT_WORDS[kind]; return w ? (technical() ? w[1] : w[0]) : String(kind || "").replace(/_/g, " "); }
export function activityLine(text) {
  let t = plurals(text);
  if (technical()) return t;
  t = t.replace(/^(T-\d+) round (\d+): gate (failed|passed)$/, (m, id, n, v) => "ran the quality check on task " + id + ": " + v + " (" + ordinal(Number(n)) + " try)")
    .replace(/^contract compiled$/, "fixed the build plan").replace(/^change triaged$/, "sorted a change request")
    .replace(/^intake done$/, "finished the first questions").replace(/^answer on question$/, "answered a question");
  return t;
}
function ordinal(n) { return n + (n % 10 === 1 && n % 100 !== 11 ? "st" : n % 10 === 2 && n % 100 !== 12 ? "nd" : n % 10 === 3 && n % 100 !== 13 ? "rd" : "th"); }

/* A due date for a person: "9 Dec" (or "9 Dec 2027" in another year). */
export function dayWord(iso) {
  const d = new Date(String(iso || "").slice(0, 10) + "T12:00:00");
  if (Number.isNaN(d.getTime())) return String(iso || "");
  const s = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return d.getFullYear() === new Date().getFullYear() ? s : s + " " + d.getFullYear();
}

// Settings words: [plain, technical]. The raw value is in the term's tooltip.
const AMBITION_WORDS = { explore: ["quick try-out", "explore"], demo: ["demo for the owner", "demo"], pilot: ["pilot", "pilot"],
  production: ["live service", "production"] };
export function ambitionWord(m) { const w = AMBITION_WORDS[m]; return w ? (technical() ? w[1] : w[0]) : m; }
const AMBITION_LONG = { explore: "Quick try-out: a bare working version to test the idea; nobody relies on it",
  demo: "Demo: a version the owner can try and show", pilot: "Pilot: real people use it for a while, with care",
  production: "Live service: a product people depend on" };
export function ambitionLong(m, fallback) { return technical() ? fallback || m : AMBITION_LONG[m] || fallback || m; }
// How much the AI may do on its own (the autonomy cap 1 to 5), in words.
const AUTONOMY_WORDS = { 1: "AI acts alone rarely", 2: "AI acts alone sometimes", 3: "AI acts alone often", 4: "AI may build and deliver on its own",
  5: "AI may take it live on its own" };
export function autonomyWord(n) { return technical() ? "Autonomy " + n : AUTONOMY_WORDS[n] || "AI independence " + n; }

// Key figures on Home: the basis of each, said for the reader. The technical basis is the server's own.
const BASIS_WORDS = {
  decisions: "Decisions that wait for someone, across all projects",
  first_round: "Share of tasks that passed the automatic quality check at the first try",
  proven: "Agreed checks shown to work, of all agreed checks; the rest have not been tested yet",
  in_flight: "Projects being worked on now, of all projects",
  in_use: "Projects live and in use, of all projects in the catalogue",
};
export function basisWord(key, basis) { return technical() ? basis : BASIS_WORDS[key] || basis; }

/* Insights tile and chart labels (kernel/insights): [plain, technical]. */
const INSIGHT_WORDS = {
  posture_kept: ["Working rules followed", "Posture kept"], posture_unmet: ["Rules not yet met", "Posture requirements unmet"],
  unmet: ["Rules not yet met", "What postures still require"], autonomy_holds: ["Times the AI paused for approval", "Autonomy holds"],
  autonomy_capped: ["Times the AI was stopped by its limit", "Autonomy cap hits"], ledger_integrity: ["Decision records untouched", "Verified ledgers"],
  contradictions: ["Conflicts between answers", "Canon contradictions"], context_trims: ["Runs that left out part of the plan", "Runs that trimmed context"],
  context_use: ["How full the AI's reading space got", "Largest prompt against the window"], verifier_disagreements: ["AI reviewer disagreed with the tests", "Verifier disagreements"],
  fail_first: ["Tests proven able to catch a mistake", "Fail-first held"], holdout_rate: ["Hidden tests passed", "Holdout pass rate"],
  flaky_reruns: ["Checks that passed only on a second run", "Flaky reruns"],
  failures: ["Run failures (tool or job crashes)", "Run failures (harness or job crashes)"],
  gate_blocks: ["Work held back by the quality check", "Gate blocks"], merges_since_spec: ["Changes since the plan was written", "Merges since the spec"],
  repo_drift: ["Code changed outside the plan", "Repository drift"], revisions_since_release: ["Plan changes since the last release", "Contract revisions since release"],
  first_round: ["Passed the quality check first time", "First-round passes"], rounds_per_task: ["Attempts per task", "Rounds per task"],
  cost: ["AI cost", "Cloud cost"], runs: ["AI runs", "Model runs"], local_share: ["Done by AI on this computer", "On local models"],
  waiting: ["Decisions waiting", "Cards waiting"], coverage: ["Agreed checks shown to work", "Criteria proven"],
  redteam: ["Attack tests with open findings", "Red-team findings open"], secret_hits: ["Passwords or keys found in code", "Secret findings"],
  open_findings: ["Open security warnings", "Open findings"], confidential: ["Projects kept on local AI only", "Confidential projects"],
  pass_rate: ["Quality checks passed", "Gate pass rate"], compactions: ["Times the AI condensed its notes", "Compactions"],
};
export function insightWord(key, label) { const w = INSIGHT_WORDS[key]; return w ? (technical() ? w[1] : w[0]) : label; }
// The Insights tabs: [plain, technical].
const INSIGHT_TABS = { drift: ["Is the plan still current?", "Context drift"], qa: ["Quality", "QA"], usage: ["Usage and cost", "Usage"] };
export function insightTab(key, label) { const w = INSIGHT_TABS[key]; return w ? (technical() ? w[1] : w[0]) : label; }
/* "5 build and verify leads the stages with 2 projects, 50% of the whole." → "Most projects (2 of 4) are in Build and check". */
export function leadLine(line) {
  const m = /^(.+?) leads the (\w+) with (\d+) (\w+?)s?, (\d+)% of the whole\.?$/.exec(String(line || ""));
  if (!m) return line;
  const [, who, what, n, unit, share] = m;
  const total = Math.round(Number(n) * 100 / Math.max(1, Number(share)));
  const name = /^\d+ /.test(who) ? stageWord(Number(who.split(" ")[0]), who.replace(/^\d+ /, "")) : who;
  if (what === "stages") return Number(n) === total ? "All " + (total === 1 ? "the project is" : total + " projects are") + " in " + name + "."
    : "Most projects (" + n + " of " + total + ") are in " + name + ".";
  return cap1(name) + ": " + n + " of " + total + " " + what + ".";
}
/* "To measure it: <a command>": a business reader gets the cockpit's own way, a technical one the command too. */
export function measureHow(how) {
  const t = String(how || "");
  if (!t || /^nothing to do/i.test(t)) return "";
  if (technical()) return t;
  if (/checks enable|Health tab/i.test(t)) return "turn on a check in the project's Health view";
  if (/tracking set/i.test(t)) return "set a deadline and budget on the project's On track? view";
  if (/posture set/i.test(t)) return "choose working rules in the project's settings";
  if (/rihmasto |python -m|kernel\/|\.json/.test(t)) return "ask IT or a developer to set it up";
  return t;
}

/* A record's time in the reader's own clock ("10:56"), not UTC; the full stamp stays in the tooltip. */
export function localTime(iso) {
  const d = new Date(String(iso || ""));
  return Number.isNaN(d.getTime()) ? String(iso || "").slice(11, 16) : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
export function localDateTime(iso) {
  const d = new Date(String(iso || ""));
  return Number.isNaN(d.getTime()) ? String(iso || "")
    : d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/* An Inbox card's lead line (kernel/card_words.py writes "<what>: <its choices>"). The choices are the buttons
   right below it, so the line says only what is asked; the request itself loses its "[embed E-001]" prefix. */
export function plainCard(c) {
  const kind = c.kind;
  const title = cardTitle(c.title).text;
  const line = String(c.plain || c.title || "");
  if (kind === "change") return pick("Change request: ", "Change: ") + title;
  if (kind === "concept") return title.replace(/^(New idea|Concept): /, pick("New idea: ", "Concept: "));
  if (kind === "update") return cardTitle(c.title).text;
  if (kind === "escalation") {
    const m = /^The task '(.*)' failed its checks (.+?)(?::|$)/.exec(line);
    const n = /after (\d+) round/.exec(String(c.title || ""));
    const task = (c.refs || {}).task || "";
    if (technical()) {
      return (task || "The task") + " failed its gate in " + (n ? n[1] + (n[1] === "1" ? " round" : " rounds") : "more than one round")
        + ": retry, accept as is (merge despite the failed gate) or stop";
    }
    if (m) return "The work “" + m[1] + "” failed its quality check " + m[2].replace(/^1 time$/, "once");
  }
  // any other kind: the kernel's line without its trailing list of choices
  return plurals(line.replace(/: (?:[a-z' ]+, )*[a-z' ]+ or [a-z' ]+$/, ""));
}

/* Why a stuck task is stuck, for a business reader, from the gate's objections ("fail_first: ...", "verifier: ...").
   The raw objections stay folded under Details for a developer. */
export function stuckWhy(text) {
  const t = String(text || "");
  if (technical() || !t) return "";
  const why = [];
  if (/fail_first/i.test(t)) why.push("the automatic test for this work passes even without the work, so it cannot tell whether the work is right");
  if (/verifier|judge/i.test(t)) why.push("the independent AI reviewer found a serious problem");
  if (/tests? failed|failing test|assert/i.test(t) && !why.length) why.push("its tests fail");
  if (!why.length) why.push("the quality check did not pass");
  return "Why it is stuck: " + why.join("; and ") + ". Recommended: Retry, so Rihma tries again with what the check said.";
}

/* A project's track answer in one line: the kernel's reasons, or, when none, the figures it rests on. */
export function trackSaid(r) {
  const reasons = (r && r.reasons) || [];
  if (reasons.length) return plurals(reasons.map((x) => x.why).slice(0, 2).join("; "));
  if (!r) return "";
  if (r.state === "not_measured") return pick("Not measured yet: no approved plan to compare with", r.basis || "");
  const t = r.tasks || {};
  const done = t.total !== null && t.total !== undefined ? t.done + " of " + t.total + " tasks done, " : "";
  if (r.state === "on_track") return "On track: " + done + "no overdue assumptions, no stuck work";
  return r.basis || "";
}

/* A project's forecast in words that say what will be done and what it waits for. */
export function etaSaid(f, waiting) {
  const known = (x) => x !== null && x !== undefined;
  const wait = waiting ? (waiting === 1 ? "your 1 decision" : "your " + waiting + " decisions") : "";
  if (f.tasks_total === 0) {      // no build plan yet (still being shaped): nothing was built, so nothing is "done"
    return waiting ? pick("Nothing to build yet: the plan is still being shaped. Waiting for " + wait + ".", "No contract yet; waiting on " + plural(waiting, "decision") + ".")
      : pick("Nothing to build yet: the plan is still being shaped.", "No contract yet.");
  }
  if (known(f.tasks_left) && f.tasks_left === 0) {
    return waiting ? pick("All build work is done. Waiting for " + wait + ".", "No task to build; waiting on " + plural(waiting, "decision") + ".")
      : pick("No build work left.", "No task left to build.");
  }
  if (!known(f.eta_minutes)) return "";
  const m = Math.round(f.eta_minutes);
  const time = m < 1 ? "under a minute" : m < 90 ? "about " + m + " min" : "about " + Math.round(m / 60) + " h";
  return pick("Build time left: " + time, "ETA " + time) + (wait ? ", after " + wait : "") + ".";
}
function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }
/* How many decisions a project's now line says wait ("3 decision(s) waiting: ..."), or 0. */
export function waitingCount(line) { const m = /^(\d+) decision\(s\) waiting/.exec(String(line || "")); return m ? Number(m[1]) : 0; }

/* The delivery square's five places, in the reader's words. */
export const SQUARE_WORDS = {
  needs: ["New requests", "Signals"], concept: ["New ideas to approve", "Concept validation"],
  factory: ["Projects being worked on", "Projects in the pipeline"], testing: ["People trying it", "End-user testing"],
  production: ["Live", "Production"],
};
export function squareWord(id) { const w = SQUARE_WORDS[id]; return w ? (technical() ? w[1] : w[0]) : id; }

/* A ledger event name ("evidence_exported") as words: [plain, technical]. */
const LEDGER_EVENTS = {
  evidence_exported: ["Proof package downloaded", "Evidence exported"], card_opened: ["Decision requested", "Card opened"],
  card_decided: ["Decision made", "Card decided"], change_triaged: ["Change sorted", "Change triaged"],
  pack_versioned: ["Release package updated", "Capability pack versioned"], release_reached_test: ["Release ready for testing", "Release reached test"],
  contract_compiled: ["Build plan fixed", "Contract compiled"], spec_written: ["Requirements written", "Spec written"],
  intake_done: ["First questions done", "Intake done"], model_run: ["AI model ran", "Model run"], cell_ran: ["AI build attempt", "Cell ran"],
  gate: ["Quality check", "Gate verdict"], merged: ["Work accepted", "Merged"], escalated: ["Task stuck", "Escalated"],
  assumption_made: ["Assumed an answer", "Assumption made"], question_answered: ["Question answered", "Question answered"],
  release_cut: ["Release made", "Release cut"], deployed: ["Put on a server", "Deployed"],
};
export function ledgerEvent(kind) {
  const w = LEDGER_EVENTS[kind];
  if (w) return technical() ? kind : w[0];
  return technical() ? kind : cap1(String(kind || "").replace(/_/g, " "));
}

/* Release pipeline steps ("build_image", "deploy:preview") in words. */
export function releaseStep(step) {
  if (technical()) return step;
  const s = String(step || "");
  const env = s.split(":")[1];
  if (/^build/.test(s)) return "Built";
  if (/^deploy/.test(s)) return "Put on the " + (env || "server");
  if (/^smoke/.test(s)) return "Quick check after launch" + (env ? " (" + env + ")" : "");
  if (/^holdout/.test(s)) return "Hidden tests";
  if (/^canary/.test(s)) return "Trial with a few users";
  if (/^shadow/.test(s)) return "Shadow run";
  return cap1(s.replace(/[_:]/g, " "));
}

/* A regulation control id ("ai-act:art12") with what it is about, for a reader who does not know the codes. */
const CONTROLS = { "ai-act": "EU AI Act", gdpr: "GDPR", nis2: "NIS2", "iso27001": "ISO 27001", dora: "DORA", cra: "Cyber Resilience Act" };
export function controlName(id, about) {
  const [law, art] = String(id || "").split(":");
  if (technical() || !CONTROLS[law]) return id;
  return CONTROLS[law] + (about ? ": " + about : art ? " " + art.replace(/^art/, "article ") : "");
}

/* Words no reader should meet: inflated, vague or self-referential filler. The wording test fails on any. */
export const SLOP = ["seamless", "seamlessly", "leverage", "robust", "it's important to note", "it is important to note",
  "rihmasto has", "your journey", "empower", "cutting-edge", "unlock", "delve", "effortless", "game-changer"];
/* Words a business reader should not meet unexplained (outside a term, code or a record's own text). */
export const JARGON = ["gate", "gates", "fail-first", "holdout", "canon", "ledger", "cell", "cells", "round", "rounds", "contract",
  "criterion", "criteria", "escalation", "attestation", "provenance", "sbom", "sha256", "hash", "merged", "merge", "commit",
  "mcp", "payload", "refs", "verdict", "judge", "posture", "triage", "stale", "ci", "repository", "json", "kernel", "apparatus",
  "canary", "harness", "persona", "spec"];
