/* Postures: one choice that sets how a project runs, tuned by priority weights (kernel/posture.py).
   The New project dialog's posture picker, and the project header's Posture chip and dialog. Every
   effect is the kernel's rule: what a posture will do is asked of POST /api/postures/preview and shown
   before anyone chooses; this page decides nothing. A change is signed and goes through PUT
   /api/projects/<pid>/posture, which says what it changes now and later. */

import {
  S, $$, h, fill, icon, chip, api, say, signed, needPerson, AuthError, nav, enc, segmented, openModal, closeModal,
  personaLabel, orList, fmtAt, cap,
} from "./core.js";

const GROUPS = [["intake", "The panel"], ["spec", "The spec"], ["gates", "The gates"], ["people", "People"]];
// One line for the live region: the preview itself is read when the person moves to it, never announced whole.
function said(res) {
  const e = (res && res.effects) || {};
  return e.label ? "Preview: " + e.label + ", " + e.maturity + ", mode " + e.mode + ", autonomy " + e.autonomy + "." : "";
}
const WEIGHT_LABEL = { ux: "UX", security: "Security", compliance: "Compliance", speed: "Speed", cost: "Cost" };
const MODE_ORDER = ["assume", "mixed", "socratic"];

function info() { return (S.meta && S.meta.postures) || { postures: [], weights: {}, setters: [], looseners: [] }; }
export function postureOf(id) { return info().postures.find((p) => p.id === id) || null; }

// What a posture will do, in the kernel's own words: four groups, and any weight a floor raised.
export function previewBlock(out, heading) {
  const lines = (out && out.lines) || {};
  return h("div", { class: "pst-preview" },
    heading ? h("h3", { class: "label-h" }, heading) : null,
    h("div", { class: "pst-groups" }, GROUPS.map(([k, label]) => (lines[k] && lines[k].length
      ? h("section", { class: "pst-group", "aria-label": label },
        h("h4", null, label), h("ul", { class: "plain small" }, lines[k].map((x) => h("li", null, x))))
      : null))),
    lines.raised && lines.raised.length
      ? h("p", { class: "note warning small" }, icon("alert"), h("span", null, "Raised to the posture's floor: " + lines.raised.join("; ") + "."))
      : null);
}

// A radiogroup of cards with one tab stop; the arrow keys move and choose, as the work profile does.
function cardGroup(label, items, value, onChange) {
  const grid = h("div", { class: "prof-grid pst-grid", role: "radiogroup", "aria-label": label });
  let current = value;
  const draw = () => $$(".prof-card", grid).forEach((b) => {
    const on = b.dataset.key === "posture:" + current;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on ? 0 : -1;
  });
  const choose = (id) => { current = id; draw(); onChange(id); };
  fill(grid, items.map((p) => {
    const b = h("button", { type: "button", role: "radio", "aria-checked": "false", class: "prof-card pst-card",
      "data-key": "posture:" + p.id },
    h("span", { class: "prof-top" }, h("span", { class: "cat-ic" }, icon(p.icon)),
      p.autonomy ? chip("neutral", "gauge", "Autonomy " + p.autonomy, { tip: "How far the factory goes alone before a person's go-ahead" }) : null),
    h("b", null, p.label), h("span", { class: "prof-s" }, p.summary));
    b.addEventListener("click", () => choose(p.id));
    return b;
  }));
  grid.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    const all = $$(".prof-card", grid);
    const i = all.indexOf(document.activeElement);
    if (i < 0 || !step) return;
    e.preventDefault();
    const next = all[(i + step + all.length) % all.length];
    choose(next.dataset.key.split(":")[1]);
    next.focus();
  });
  draw();
  return grid;
}

// The weights from 0 to 3, each a segmented control; a value under the posture's floor is not offered.
function weightRows(p, weights, onChange) {
  return h("div", { class: "pst-weights", role: "group", "aria-label": "Priority weights, 0 to 3" },
    Object.keys(WEIGHT_LABEL).map((k) => {
      const floor = (p.floors || {})[k] || 0;
      const seg = segmented("w-" + k, [0, 1, 2, 3].map((n) => [n, String(n)]), weights[k], (v) => { weights[k] = v; onChange(); },
        { label: WEIGHT_LABEL[k] + " priority, 0 to 3" });
      $$(".seg-b", seg).forEach((b) => { if (Number(b.dataset.key.split(":")[1]) < floor) b.disabled = true; });
      return h("div", { class: "pst-w" },
        h("span", { class: "pst-wl", tip: info().weights[k] || "" }, WEIGHT_LABEL[k]), seg,
        floor ? h("small", { class: "muted" }, "at least " + floor) : null);
    }));
}

function choiceSeg(name, label, options, value, onChange) {
  return segmented(name, options.map((m) => [m, cap(m)]), value, onChange, { label });
}

// The New project dialog's "How it runs": a posture (or none, as before), its weights, the maturity and
// mode it allows, and the kernel's preview. ``profile`` gives the chosen work profile (whether it has
// screens); a click or key in ``watch`` (the profile grid) asks for the preview again.
export function postureSection(opts) {
  const o = opts || {};
  // No posture unless a person picks one: nothing holds a daily user by surprise; Balanced and the rest are one click away.
  const state = { posture: "", weights: {}, maturity: null, mode: null };
  const body = h("div", { class: "pst-body" });
  const out = h("div", { class: "pst-out" });
  const live = h("p", { class: "vh", role: "status" });
  const custom = { id: "", label: "No posture", icon: "settings", summary: "Choose the maturity and mode yourself; the autonomy cap alone, as before." };
  let timer = null;
  let asked = 0;
  const preview = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const n = ++asked;                  // a preview still on its way for an earlier choice is dropped
      if (!state.posture) {
        fill(out, h("p", { class: "note small" }, icon("info"), h("span", null, "No posture: the project runs by the maturity and mode you choose, "
          + "with the autonomy cap alone and the maturity's own gates, as before.")));
        live.textContent = "No posture.";
        return;
      }
      try {
        const res = await api("POST", "/api/postures/preview", { posture: state.posture, weights: state.weights,
          maturity: state.maturity, mode: state.mode, profile: o.profile ? o.profile() : null });
        if (n !== asked) return;
        fill(out, previewBlock(res, "What " + postureOf(state.posture).label + " will do"));
        live.textContent = said(res);
      } catch (e) {
        if (!(e instanceof AuthError) && n === asked) fill(out, h("p", { class: "note warning small" }, icon("alert"), h("span", null, e.message)));
      }
    }, 120);
  };
  const drawBody = () => {
    const p = postureOf(state.posture);
    const all = Object.keys((S.meta && S.meta.maturities) || {});
    if (!p) {
      state.maturity = state.maturity && all.includes(state.maturity) ? state.maturity : "demo";
      state.mode = state.mode || "mixed";
      fill(body, h("div", { class: "row2" },
        h("div", { class: "field" }, h("span", { class: "label-h" }, "Maturity"), choiceSeg("np-maturity", "Maturity", all, state.maturity, (v) => { state.maturity = v; })),
        h("div", { class: "field" }, h("span", { class: "label-h" }, "Mode"), choiceSeg("np-mode", "Mode", MODE_ORDER, state.mode, (v) => { state.mode = v; }))));
      preview();
      return;
    }
    state.weights = Object.assign({}, p.weights);
    state.maturity = p.maturity;
    state.mode = p.mode;
    const modes = MODE_ORDER.slice(MODE_ORDER.indexOf(p.mode));
    fill(body,
      h("div", { class: "field" }, h("span", { class: "label-h" }, "Priorities"), weightRows(p, state.weights, preview),
        h("small", { class: "muted" }, "Each from 0 to 3. They shape the panel's questions, the spec's topics, which findings block and how much waits for a person.")),
      h("div", { class: "row2" },
        h("div", { class: "field" }, h("span", { class: "label-h" }, "Maturity"),
          choiceSeg("np-maturity", "Maturity", p.maturities, state.maturity, (v) => { state.maturity = v; preview(); })),
        h("div", { class: "field" }, h("span", { class: "label-h" }, "Mode"),
          choiceSeg("np-mode", "Mode", modes, state.mode, (v) => { state.mode = v; preview(); }))));
    preview();
  };
  const group = cardGroup("Posture", [...info().postures, custom], state.posture, (id) => { state.posture = id; drawBody(); });
  if (o.watch) ["click", "keydown"].forEach((ev) => o.watch.addEventListener(ev, () => setTimeout(preview, 0)));
  drawBody();
  const el = h("section", { class: "pst-section", "aria-labelledby": "np-posture-h", "data-control": "posture" },
    h("h3", { id: "np-posture-h", class: "label-h" }, "How it runs"),
    h("p", { class: "muted small" }, "A posture sets the mode, the maturity, the gates and how much waits for a person. You see what it will do before you create the project."),
    group, body, out, live);
  const value = () => (state.posture
    ? { posture: state.posture, weights: state.weights, maturity: state.maturity, mode: state.mode }
    : { maturity: state.maturity, mode: state.mode });
  return { el, value };
}

// -- a project's posture: the header chip and its dialog --------------------------------------------

// ``open`` opens the Posture dialog; by default at once (the Project settings dialog swaps one for the other).
export function postureChip(p, open) {
  const rec = (p.meta || {}).posture;
  const known = rec && postureOf(rec.name);
  const b = h("button", { type: "button", class: "chip " + (known ? "accent" : "nm") + " pst-chip", "data-control": "posture",
    "data-key": "posture", "aria-haspopup": "dialog",
    tip: known ? known.summary + " Open what it does and what holds the project." : "No posture: the project runs by its mode, maturity and autonomy cap. Open to choose one." },
  icon(known ? known.icon : "sliders"), h("span", null, known ? "Posture: " + known.label : "No posture"));
  b.addEventListener("click", () => (open ? open() : openPosture(p)));
  return b;
}

function changeList(title, items, tone) {
  return items && items.length ? h("section", { class: "pst-group" + (tone ? " " + tone : ""), "aria-label": title },
    h("h4", null, title), h("ul", { class: "plain small" }, items.map((x) => h("li", null, x)))) : null;
}

function changeForm(p, view, onDone) {
  const pid = p.meta.id;
  const current = (view.posture || {}).posture || "balanced";
  const state = { posture: current, weights: Object.assign({}, ((view.posture || {}).weights) || (postureOf(current) || {}).weights || {}),
    maturity: p.meta.maturity, mode: p.meta.mode };
  const body = h("div", { class: "pst-body" });
  const out = h("div", { class: "pst-out" });
  const live = h("p", { class: "vh", role: "status" });
  const reason = h("input", { id: "pst-reason", "data-key": "pst-reason", maxlength: "2000", autocomplete: "off",
    placeholder: "for example: the pilot now runs on customer data" });
  const save = h("button", { type: "submit", class: "btn human primary" }, "Set the posture");
  let timer = null;
  let asked = 0;
  const preview = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const n = ++asked;
      try {
        const res = await api("POST", "/api/postures/preview", { posture: state.posture, weights: state.weights, project: pid,
          maturity: state.maturity, mode: state.mode });
        if (n !== asked) return;
        live.textContent = said(res) + (res.loosens && res.loosens.length ? " It loosens the posture." : "");
        fill(out, h("div", { class: "pst-change" },
          res.loosens && res.loosens.length ? h("p", { class: "note warning small" }, icon("alert"),
            h("span", null, "This loosens the posture (" + res.loosens.join("; ") + "): a " + orList(info().looseners) + " may.")) : null,
          changeList("What changes now", res.now), changeList("What changes later", res.later),
          !(res.now || []).length && !(res.later || []).length ? h("p", { class: "muted small" }, "Nothing changes.") : null),
        previewBlock(res, "What " + postureOf(state.posture).label + " will do"));
      } catch (e) {
        if (!(e instanceof AuthError) && n === asked) fill(out, h("p", { class: "note warning small" }, icon("alert"), h("span", null, e.message)));
      }
    }, 120);
  };
  // Another posture starts from its own weights and mode; the project keeps its maturity where the posture
  // runs at it (as the kernel does).
  const drawBody = (fresh) => {
    const pp = postureOf(state.posture);
    if (fresh) Object.assign(state, { weights: Object.assign({}, pp.weights), mode: pp.mode, maturity: p.meta.maturity });
    if (!pp.maturities.includes(state.maturity)) state.maturity = pp.maturity;
    const modes = MODE_ORDER.slice(MODE_ORDER.indexOf(pp.mode));
    if (!modes.includes(state.mode)) state.mode = pp.mode;
    fill(body, h("div", { class: "field" }, h("span", { class: "label-h" }, "Priorities"), weightRows(pp, state.weights, preview)),
      h("div", { class: "row2" },
        h("div", { class: "field" }, h("span", { class: "label-h" }, "Maturity"),
          choiceSeg("pst-maturity", "Maturity", pp.maturities, state.maturity, (v) => { state.maturity = v; preview(); })),
        h("div", { class: "field" }, h("span", { class: "label-h" }, "Mode"),
          choiceSeg("pst-mode", "Mode", modes, state.mode, (v) => { state.mode = v; preview(); }))));
    preview();
  };
  const group = cardGroup("Posture", info().postures, state.posture, (id) => { state.posture = id; drawBody(true); });
  drawBody(false);
  const form = h("form", { class: "au-form pst-form", novalidate: true, "aria-label": "Set the posture of " + p.meta.title },
    group, body, out, live,
    h("div", { class: "field" }, h("label", { for: "pst-reason" }, "Reason (required, recorded with your name)"), reason),
    h("div", { class: "btns" }, save));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!reason.value.trim()) { say("A posture change needs a reason: it is recorded with your name.", "warning"); reason.focus(); return; }
    if (!needPerson()) return;
    save.disabled = true;
    try {
      const out = await api("PUT", "/api/projects/" + enc(pid) + "/posture", Object.assign({ posture: state.posture, weights: state.weights,
        maturity: state.maturity, mode: state.mode, reason: reason.value.trim() }, signed()));
      say(p.meta.title + ": the posture is " + postureOf(out.posture).label + ", signed by " + S.person.trim()
        + "." + (out.now && out.now.length ? " Now: " + out.now.join("; ") + "." : ""), "good");
      onDone();
      closeModal();
    } catch (err) {
      if (!(err instanceof AuthError)) say(err.message, "critical");
      if (save.isConnected) { save.disabled = false; save.focus(); }
    }
  });
  return form;
}

export async function openPosture(p) {
  const pid = p.meta.id;
  let view = null;
  try {
    view = await api("GET", "/api/projects/" + enc(pid) + "/posture");
  } catch (e) {
    if (!(e instanceof AuthError)) say(e.message, "critical");
    return;
  }
  let changed = false;
  const rec = view.posture;
  const known = rec && postureOf(rec.posture);
  const may = (info().setters || []).includes(S.persona);
  const body = h("div", { class: "au-body pst-dialog" },
    known ? h("p", null, h("b", null, known.label), ": " + known.summary) : h("p", null, view.note || "No posture."),
    rec ? h("p", { class: "muted small" }, "Chosen by " + rec.chosen_by + (rec.persona ? " (" + personaLabel(rec.persona) + ")" : "")
      + (rec.at ? ", " + fmtAt(rec.at) : "") + (rec.reason ? ": “" + rec.reason + "”" : "") + ". The autonomy cap is " + view.cap + ".")
      : h("p", { class: "muted small" }, "The autonomy cap is " + view.cap + "."),
    rec ? h("section", { "aria-labelledby": "pst-holds-h" }, h("h3", { id: "pst-holds-h", class: "label-h" }, "What holds the project now"),
      (view.holds || []).length ? h("ul", { class: "plain small" }, view.holds.map((x) => h("li", null, x)))
        : h("p", { class: "muted small" }, "Nothing the posture asks for is missing now.")) : null,
    rec ? previewBlock(view, "What it does") : null);
  if (may) {
    body.append(h("h3", { class: "label-h" }, rec ? "Change the posture" : "Choose a posture"),
      changeForm(p, view, () => { changed = true; }));
  } else {
    body.append(h("p", { class: "muted small" }, "A " + orList(info().setters) + " persona chooses the posture, always with a reason; loosening it needs a "
      + orList(info().looseners) + "."));
  }
  openModal("Posture · " + p.meta.title, body, { icon: "sliders", wide: true, onClose: () => { if (changed && nav.rerender) nav.rerender(); } });
}
