/* Live progress for long jobs (kernel/progress.py, FR-PRG1): one view for an assessment, an adoption, a folder
   scan, and any job that reports a plan and its steps.

   A job's plan is a row of groups ("Reading the code", "Rule checks", "The panel", "The record"), each a set of
   tiles, one per step. A tile fills as its step runs and ends; its state is said by its glyph and its words, never
   by colour alone: a dashed ring waits, a turning arrow runs (still when the person asked for less motion), a
   tick is done, a cross failed, a dash was skipped. A done tile carries its count (findings, proposals, files) as
   it lands. Above the tiles: the steps done of all, a thin segmented meter, the time it has taken and an honest
   estimate (from earlier runs of the same kind on the same project, or "first run: no estimate"), and the step
   running now in words. Below: the findings so far, newest first; pressing a tile shows that area's own.

   `watch()` polls a progress route with only what changed since its cursor and keeps the view up to date in
   place, so focus and the running animation are not lost every second; when the job ends it waits a moment on
   the filled tiles, then hands over to the result (``onEnd``). `strip()` draws the same plan small and still,
   for Ask Rihma, the Overview card, a guided journey or a folder scan. Colours: the progress fill is the first
   categorical slot (one hue, light track to full), a failed step the critical status mark; both validated with
   the dataviz method (tests/insights_palette.py) in both themes. */

import { h, fill, icon, api, signed, needPerson, say, plural, cap, enc, AuthError } from "./core.js";

const GLYPH = { waiting: "dashed", running: "refresh", done: "check-circle", failed: "x-circle", skipped: "arrow-right" };
const WORD = { waiting: "Waiting", running: "Running", done: "Done", failed: "Failed", skipped: "Skipped" };
const COUNT_WORD = { findings: ["finding", "findings"], proposed: ["proposal", "proposals"], files: ["file", "files"],
  opened: ["opened", "opened"], passed: ["passed", "passed"], not_measured: ["not measured", "not measured"],
  not_applicable: ["not applicable", "not applicable"], dropped: ["dropped", "dropped"] };
const PRIMARY = ["findings", "proposed", "files", "opened"];
const SEV_TONE = { critical: "critical", high: "critical", medium: "warning", low: "info", info: "neutral" };
const POLL_MS = 1000;
const HANDOVER_MS = 1400;
const SHOWN = 14;
const LIVE = new Map();          // url -> the watcher running for it, so a re-render keeps the same view

// -- the model: a job's progress, merged from what changed since the cursor --------------------------------------

export function blank() {
  return { cursor: 0, plan: [], steps: {}, findings: {}, state: null, why: "", now: "", elapsed_s: 0, estimate: {},
    steps_done: 0, steps_total: 0, result: null, title: "", kind: "", cancel_asked: null, at: Date.now() };
}

export function merge(m, got) {
  if (!got) return m;
  if (got.whole) {
    m.plan = got.plan || [];
    m.steps = Object.assign({}, got.steps || {});
    m.findings = {};
    Object.entries(got.findings || {}).forEach(([sid, list]) => { m.findings[sid] = list.slice(); });
  }
  (got.whole ? [] : got.events || []).forEach((e) => {      // a whole answer already holds what its events say
    if (e.kind === "plan") m.plan = e.plan || m.plan;
    if (e.step && e.state) m.steps[e.step] = e.state;
    if (e.kind === "found" && e.step) m.findings[e.step] = (m.findings[e.step] || []).concat(e.findings || []);
  });
  ["cursor", "state", "why", "now", "elapsed_s", "estimate", "steps_done", "steps_total", "result", "title", "kind",
    "cancel_asked", "started_at"].forEach((k) => { if (got[k] !== undefined) m[k] = got[k]; });
  m.at = Date.now();
  return m;
}

function elapsedNow(m) {
  const extra = m.state === "running" ? (Date.now() - m.at) / 1000 : 0;
  return Math.max(0, Number(m.elapsed_s || 0) + extra);
}

export function duration(secs) {
  const s = Math.round(secs);
  if (s < 60) return s + " s";
  const min = Math.floor(s / 60);
  return min < 60 ? min + " min " + String(s % 60).padStart(2, "0") + " s" : Math.floor(min / 60) + " h " + (min % 60) + " min";
}

function countWord(key, n) { const w = COUNT_WORD[key] || [key.replace(/_/g, " "), key.replace(/_/g, " ")]; return n === 1 ? w[0] : w[1]; }

// The tile's headline number and its word: what landed (findings, proposals, files), else what was found so far.
function headline(s) {
  const c = s.counts || {};
  const key = PRIMARY.find((k) => typeof c[k] === "number");
  if (key) return [c[key], countWord(key, c[key])];
  if (s.state === "running" && s.found) return [s.found, countWord("findings", s.found)];
  return null;
}

function rest(s) {
  const c = s.counts || {};
  const key = PRIMARY.find((k) => typeof c[k] === "number");
  return Object.entries(c).filter(([k, v]) => k !== key && typeof v === "number" && v > 0).map(([k, v]) => v + " " + countWord(k, v)).join(" · ");
}

function usually(secs) { return "usually " + (secs < 1 ? "under a second" : duration(secs)); }

function caption(s, m) {
  if (s.state === "running") {
    const ran = s.t0 === null || s.t0 === undefined ? 0 : Math.max(0, elapsedNow(m) - s.t0);
    return duration(ran) + (s.expected_s !== null && s.expected_s !== undefined ? " · " + usually(s.expected_s) : " · first time timed");
  }
  if (s.state === "failed" || s.state === "skipped") return s.why || "";
  if (s.state === "waiting") return s.expected_s !== null && s.expected_s !== undefined ? cap(usually(s.expected_s)) : "";
  return rest(s) || s.said || "";
}

function tileLabel(s, m) {
  const head = headline(s);
  const said = caption(s, m);
  return s.label + ": " + WORD[s.state].toLowerCase() + (head ? ", " + head[0] + " " + head[1] : "") + (said ? ". " + said : "")
    + (s.by ? ". By " + s.by : "");
}

function fillOf(s, m) {
  if (s.state === "done" || s.state === "failed") return 100;
  if (s.state !== "running" || !s.expected_s) return 0;
  const ran = Math.max(0, elapsedNow(m) - (s.t0 || 0));
  return Math.min(92, Math.round((ran / s.expected_s) * 100));
}

// -- drawing ----------------------------------------------------------------------------------------------------

function findingItem(f, label) {
  const tone = SEV_TONE[f.severity] || "neutral";
  return h("li", { class: "prg-fi" },
    f.severity ? h("span", { class: "chip " + tone + " prg-sev" }, h("span", null, cap(f.severity))) : null,
    f.id ? h("b", { class: "mono" }, f.id) : null,
    h("span", { class: "prg-ft" }, f.title || f.key || ""),
    label || f.panel ? h("span", { class: "prg-fa muted" }, [label, f.panel ? "proposed" : ""].filter(Boolean).join(" · ")) : null);
}

function allSteps(m) { return m.plan.flatMap((g) => g.steps.map((sid) => m.steps[sid]).filter(Boolean)); }

class View {
  constructor(opts) {
    this.o = opts;
    this.m = blank();
    this.pick = null;
    this.built = "";
    this.el = h("section", Object.assign({ class: "prg card" + (opts.compact ? " prg-compact" : ""), "aria-labelledby": opts.id + "-h",
      "data-kind": "" }, opts.attrs || {}));
  }

  build() {
    const o = this.o;
    this.title = h("h3", { class: "card-t prg-title", id: o.id + "-h" });
    this.count = h("span", { class: "prg-count" });
    this.time = h("span", { class: "prg-time" });
    this.est = h("span", { class: "prg-est" });
    this.cancelBtn = o.cancelUrl ? h("button", Object.assign({ type: "button", class: "btn small quiet prg-cancel" }, o.cancelAttrs || {}),
      icon("stop"), h("span", { class: "lbl" }, "Cancel")) : null;
    if (this.cancelBtn) this.cancelBtn.addEventListener("click", () => this.cancel());
    this.meter = h("div", { class: "prg-meter", role: "progressbar", "aria-valuemin": "0" });
    this.nowLine = h("p", { class: "prg-now", role: "status", "aria-live": "polite" });
    this.groups = h("div", { class: "prg-groups" });
    this.foundHead = h("h4", { class: "prg-fh" });
    this.foundAll = h("button", { type: "button", class: "btn small quiet prg-all", hidden: true }, h("span", { class: "lbl" }, "Show every area"));
    this.foundAll.addEventListener("click", () => { this.pick = null; this.draw(); });
    this.foundList = h("ul", { class: "plain prg-fl" });
    this.found = o.compact ? null : h("div", { class: "prg-found" }, h("div", { class: "prg-fhead" }, this.foundHead, this.foundAll), this.foundList);
    fill(this.el,
      h("header", { class: "card-head prg-head" }, h("span", { class: "card-ic" }, icon(o.icon || "gauge")), this.title,
        h("span", { class: "card-tools" }, this.cancelBtn)),
      h("div", { class: "prg-meta" }, this.count, this.time, this.est),
      this.meter, this.nowLine, this.groups, this.found, o.footer || null);
  }

  // The tiles are built once per plan; afterwards only their state, words and fill change.
  buildPlan() {
    const m = this.m;
    this.tiles = {};
    this.segs = {};
    fill(this.meter, allSteps(m).map((s) => { const seg = h("span", { class: "prg-seg" }); this.segs[s.id] = seg; return seg; }));
    fill(this.groups, m.plan.map((g) => {
      const gc = h("span", { class: "prg-gc" });
      const tiles = g.steps.map((sid) => this.tile(m.steps[sid])).filter(Boolean);
      const el = h("div", { class: "prg-group", "data-group": g.id, role: "group", "aria-label": g.label },
        h("div", { class: "prg-gh" }, h("span", { class: "prg-gl" }, g.label), g.parallel ? h("span", { class: "prg-par" }, "at once") : null, gc),
        h("ul", { class: "plain prg-tiles" + (tiles.length === 1 ? " one" : "") }, tiles.map((t) => h("li", null, t))));
      el._count = gc;
      el._steps = g.steps;
      return el;
    }));
    this.built = m.plan.map((g) => g.id + ":" + g.steps.join(",")).join("|");
  }

  tile(s) {
    if (!s) return null;
    const b = h("button", { type: "button", class: "prg-tile", "data-step": s.id, "aria-pressed": "false" },
      h("span", { class: "prg-tt" }, h("span", { class: "prg-glyph" }), h("span", { class: "prg-tl" }, s.label)),
      h("span", { class: "prg-tn" }, h("b", { class: "prg-num" }), h("span", { class: "prg-nw" })),
      h("span", { class: "prg-tc" }), h("span", { class: "prg-tb" }),
      h("span", { class: "prg-bar", "aria-hidden": "true" }, h("span", { class: "prg-fill" })));
    if (this.o.compact) b.disabled = true;
    else b.addEventListener("click", () => { this.pick = this.pick === s.id ? null : s.id; this.draw(); });
    this.tiles[s.id] = b;
    return b;
  }

  drawTile(s) {
    const b = this.tiles[s.id];
    if (!b) return;
    const m = this.m;
    if (b.dataset.state !== s.state) {
      b.dataset.state = s.state;
      fill(b.querySelector(".prg-glyph"), icon(GLYPH[s.state] || "dashed"));
    }
    const head = headline(s);
    b.querySelector(".prg-num").textContent = head ? String(head[0]) : "";
    b.querySelector(".prg-nw").textContent = head ? head[1] : WORD[s.state];
    b.querySelector(".prg-tc").textContent = caption(s, m);
    b.querySelector(".prg-tb").textContent = s.by ? s.by : "";
    b.classList.toggle("has-by", !!s.by);
    b.classList.toggle("found", !!(head && head[0]));
    b.classList.toggle("open", s.state === "running" && !s.expected_s);
    b.querySelector(".prg-fill").style.width = fillOf(s, m) + "%";
    b.setAttribute("aria-label", tileLabel(s, m));
    b.setAttribute("aria-pressed", String(this.pick === s.id));
    const seg = this.segs[s.id];
    if (seg) seg.dataset.state = s.state;
  }

  draw() {
    const m = this.m;
    if (!this.title) this.build();
    const key = m.plan.map((g) => g.id + ":" + g.steps.join(",")).join("|");
    if (key !== this.built) this.buildPlan();
    this.el.dataset.state = m.state || "waiting";
    this.el.dataset.kind = m.kind || "";
    this.title.textContent = m.title || this.o.title || "Working";
    const total = m.steps_total || allSteps(m).length;
    const done = m.steps_done || 0;
    this.count.textContent = done + " of " + plural(total, "step");
    this.meter.setAttribute("aria-valuemax", String(total));
    this.meter.setAttribute("aria-valuenow", String(done));
    this.meter.setAttribute("aria-valuetext", done + " of " + total + " steps done");
    this.meter.setAttribute("aria-label", (m.title || "Progress") + ": steps done");
    this.tickTime();
    const now = m.state === "done" && this.o.doneWords ? this.o.doneWords(m) : m.now || "Starting…";
    if (this.nowLine.dataset.said !== now) {
      this.nowLine.dataset.said = now;
      fill(this.nowLine, h("span", { class: "prg-pulse", "aria-hidden": "true" }), h("span", null, now));
    }
    allSteps(m).forEach((s) => this.drawTile(s));
    this.m.plan.forEach((g, i) => {
      const el = this.groups.children[i];
      if (!el) return;
      const ss = g.steps.map((sid) => m.steps[sid]).filter(Boolean);
      el._count.textContent = ss.filter((s) => ["done", "failed", "skipped"].includes(s.state)).length + " of " + ss.length;
      el.dataset.state = ss.some((s) => s.state === "running") ? "running"
        : ss.every((s) => ["done", "failed", "skipped"].includes(s.state)) ? "done" : "waiting";
    });
    if (this.cancelBtn) {
      this.cancelBtn.hidden = m.state !== "running";
      this.cancelBtn.disabled = !!m.cancel_asked;
      this.cancelBtn.querySelector(".lbl").textContent = m.cancel_asked ? "Stopping…" : "Cancel";
    }
    if (this.found) this.drawFound();
  }

  tickTime() {
    const m = this.m;
    this.time.textContent = (m.state === "running" ? "" : "Took ") + duration(elapsedNow(m)) + (m.state === "running" ? " so far" : "");
    const said = m.state === "running" ? ((m.estimate || {}).said || "") : "";
    this.est.textContent = said;
    this.est.hidden = !said;
    Object.values(this.m.steps).forEach((s) => { if (s.state === "running") this.drawTile(s); });
  }

  drawFound() {
    const m = this.m;
    const pick = this.pick && m.steps[this.pick];
    const ids = pick ? [this.pick] : allSteps(m).map((s) => s.id);
    const items = ids.flatMap((sid) => (m.findings[sid] || []).map((f) => [f, pick ? "" : (m.steps[sid] || {}).label || sid])).reverse();
    const more = ids.reduce((n, sid) => n + ((m.steps[sid] || {}).more || 0), 0);
    const total = items.length + more;
    this.foundHead.textContent = pick ? pick.label + ": " + plural(total, "finding") + " so far"
      : (m.state === "running" ? "Findings so far: " : "Findings: ") + total;
    this.foundAll.hidden = !pick;
    const shown = pick ? items : items.slice(0, SHOWN);
    fill(this.foundList, shown.length ? shown.map(([f, label]) => findingItem(f, label))
      : h("li", { class: "muted small" }, pick ? (pick.state === "waiting" ? "This area has not run yet." : "Nothing found here so far.")
        : "The findings appear here as each area ends."),
    items.length > shown.length || more ? h("li", { class: "muted small" }, "and " + (items.length - shown.length + more) + " more"
      + (pick ? "" : ": press an area to see its own")) : null);
  }

  async cancel() {
    if (!needPerson()) return;
    this.cancelBtn.disabled = true;
    try {
      const out = await api("POST", this.o.cancelUrl, signed());
      if (out.progress) { merge(this.m, Object.assign({}, out.progress, { whole: true, events: [] })); this.draw(); }
      say(out.cancelled ? "Stopping after the step that runs now; nothing is recorded." : out.why, out.cancelled ? "good" : "warn");
    } catch (e) {
      this.cancelBtn.disabled = false;
      say(e.message, "critical");
    }
  }
}

// -- watching a job ---------------------------------------------------------------------------------------------

/* Watch a job's progress route and keep its view up to date. Options: url (the progress route), cancelUrl,
   title, id, icon, control, compact; ``fresh``: ignore an ended job until the caller says the new one started
   (``release()``), so a click never shows the last run's end; ``doneWords(m)``: the end in words; ``onEnd(m)``:
   called once, a moment after the job ended, to hand over to the result. */
export function watch(opts) {
  const key = opts.url + (opts.compact ? "|small" : "");
  const old = LIVE.get(key);
  if (old && !old.stopped) { old.o.onEnd = opts.onEnd || old.o.onEnd; return old; }
  const v = new View(Object.assign({ id: "prg" }, opts));
  const w = { el: v.el, view: v, o: v.o, stopped: false, held: !!opts.fresh, ended: false, gone: 0, timer: null, ticker: null };
  const pick = (got) => got && (got.progress === undefined ? got : got.progress);
  w.release = () => { w.held = false; };
  w.stop = () => { w.stopped = true; clearTimeout(w.timer); clearInterval(w.ticker); if (LIVE.get(key) === w) LIVE.delete(key); };
  const end = () => {
    if (w.ended) return;
    w.ended = true;
    v.el.classList.add("prg-ended");
    clearInterval(w.ticker);
    setTimeout(() => { w.stop(); if (w.o.onEnd) w.o.onEnd(v.m); }, HANDOVER_MS);
  };
  const poll = async () => {
    if (w.stopped) return;
    if (!v.el.isConnected && ++w.gone > 5) { w.stop(); return; }
    if (v.el.isConnected) w.gone = 0;
    try {
      const got = pick(await api("GET", opts.url + "?since=" + (w.held ? 0 : v.m.cursor)));
      if (got && !(w.held && got.state !== "running")) {
        if (w.held) { w.held = false; v.m = blank(); }
        merge(v.m, got);
        v.draw();
        if (got.state && got.state !== "running") { end(); return; }
      }
    } catch (e) {
      if (e instanceof AuthError) { w.stop(); return; }
    }
    w.timer = setTimeout(poll, POLL_MS);
  };
  if (opts.seed) { merge(v.m, opts.seed); }
  v.draw();
  w.ticker = setInterval(() => { if (v.el.isConnected && v.m.state === "running") v.tickTime(); }, 1000);
  LIVE.set(key, w);
  poll();
  return w;
}

// -- drawing a progress that is already read ---------------------------------------------------------------------

/* The same plan, small and still: for Ask Rihma, the Overview card, a guided journey's job, a folder scan. */
export function strip(progress, opts) {
  const o = opts || {};
  const v = new View(Object.assign({ id: "prg-s-" + Math.random().toString(36).slice(2, 8), compact: true }, o));
  merge(v.m, Object.assign({ whole: true, events: [] }, progress));
  v.draw();
  if (o.link) v.el.append(h("p", { class: "prg-link" }, h("a", { href: o.link }, icon("arrow-right"), h("span", null, o.linkText || "Open it"))));
  return v.el;
}

/* A small view a caller that already polls keeps up to date (a folder scan): ``set(progress)`` redraws in place. */
export function liveStrip(opts) {
  const v = new View(Object.assign({ id: "prg-l-" + Math.random().toString(36).slice(2, 8), compact: true }, opts || {}));
  return { el: v.el, set(p) { if (!p) return; v.m = merge(blank(), Object.assign({ whole: true, events: [] }, p)); v.draw(); } };
}

/* How far a job is, in a few words: "5 of 9 areas in, 2 min so far". */
export function inWords(p) {
  if (!p) return "";
  const m = merge(blank(), Object.assign({ whole: true, events: [] }, p));
  const groups = m.plan.length;
  const done = m.plan.filter((g) => g.steps.every((sid) => ["done", "failed", "skipped"].includes((m.steps[sid] || {}).state))).length;
  return m.steps_done + " of " + m.steps_total + " steps, " + done + " of " + groups + " groups done, " + duration(elapsedNow(m))
    + (m.state === "running" ? " so far" : "");
}

/* An adopt job's or a scan's view, kept by the cockpit as ``live`` beside its own fields. */
export function jobStrip(job, opts) {
  return job && job.live ? strip(job.live, opts) : null;
}

export function progressUrl(pid, kind) { return "/api/projects/" + enc(pid) + "/" + kind + "/progress"; }

/* The Overview's card while a long job of the project runs: the same tiles, small, and a way to the job's own
   view; nothing at all when none runs. When the job ends it says how, with the way to the result. */
export function overviewCard(pid, kind, opts) {
  const o = Object.assign({ view: kind, title: "Assessing", linkText: "Open the assessment" }, opts || {});
  const slot = h("div", { class: "prg-slot" });
  const href = "#/p/" + enc(pid) + "/" + o.view;
  api("GET", progressUrl(pid, kind)).then((got) => {
    const p = got && got.progress;
    if (!p || p.state !== "running" || !slot.isConnected) return;
    const w = watch({ url: progressUrl(pid, kind), compact: true, id: "ov-prg-" + kind, title: o.title, seed: p,
      attrs: o.attrs,
      footer: h("p", { class: "prg-link" }, h("a", { href }, icon("arrow-right"), h("span", null, o.linkText))),
      onEnd: (m) => fill(slot, h("p", { class: "note", role: "status" }, icon(m.state === "done" ? "check-circle" : "info"),
        h("span", null, (m.state === "done" ? "The " + kind + " finished: " + ((m.result || {}).id || "recorded") + ". "
          : "The " + kind + " ended " + m.state + ". ")), h("a", { href }, o.linkText))) });
    fill(slot, w.el);
  }).catch(() => null);
  return slot;
}
