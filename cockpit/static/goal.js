/* Goal help and hand-off (FR-CPL1, FR-BRG1). Ask Rihma answers a goal ("hook this to Google Drive") with a plan;
   each step here is one click that opens the place where a person does it, prefilled: the change form (the
   person edits it and files it, signed), a walkthrough, a view, the hand-off dialog, or a command to copy.
   Nothing is written by the plan itself. The hand-off dialog gives a coding agent its brief: copy, download,
   or "Run it with <runner>" when cell runners are in this Rihmasto. */

import { S, h, icon, chip, button, api, enc, say, act, needPerson, signed, openModal, closeModal, nav } from "./core.js";

const STEP_BUTTON = { draft_change: ["Draft it", "edit"], walkthrough: ["Start the walkthrough", "play"],
  open: ["Open", "arrow-right"], configure: ["Open the settings", "sliders"], enable_check: ["Open Health", "pulse"],
  automation: ["Open Automations", "refresh"], command: ["Copy the command", "copy"], handoff: ["Hand off", "send"] };

async function copy(text, what) {
  try {
    await navigator.clipboard.writeText(text);
    say((what || "It") + " is copied.", "good");
    return true;
  } catch (e) {
    openModal("Copy it yourself", h("div", null, h("p", { class: "muted small" }, "The browser did not let the page copy it. Select it and copy:"),
      h("pre", { class: "ho-brief", tabindex: "0" }, text)), { icon: "copy" });
    return false;
  }
}

export function openDraftChange(pid, text) {
  const area = h("textarea", { id: "dc-text", "data-key": "dc-text", rows: "12", maxlength: "20000", "aria-label": "The change request" });
  area.value = text || "";
  const file = button("File the change", { icon: "send", kind: "primary human", key: "dc-file" });
  const box = h("div", { class: "dc" },
    h("p", { class: "muted small" }, "Rihma drafted it from your goal. Edit it, then file it: it opens a change card signed with your name, and a person decides it in the Inbox."),
    h("label", { for: "dc-text", class: "label-h" }, "The change request"), area, h("div", { class: "btns" }, file));
  file.addEventListener("click", () => act(box, async () => {
    if (!area.value.trim() || !needPerson()) return;
    const out = await api("POST", "/api/projects/" + enc(pid) + "/changes", Object.assign({ text: area.value.trim() }, signed()));
    closeModal();
    say("Filed " + out.card.id + ", signed by " + S.person.trim() + ". It waits in the Inbox.", "good");
  }));
  openModal("Draft a change request", box, { icon: "edit", wide: true });
}

async function startWalkthrough(name) {
  try {
    const m = await import("./walkthrough.js");
    await m.startWalk(name);
  } catch (e) {
    say("Walkthroughs are not in this Rihmasto yet.", "warning");
  }
}

function runStep(pid, s) {
  const a = s.action || {};
  if (a.kind === "draft_change") return openDraftChange(pid, a.text);
  if (a.kind === "walkthrough") return startWalkthrough(a.name);
  if (a.kind === "handoff") return openHandoff(pid, { to: a.to });
  if (a.route) { location.hash = a.route; return null; }
  if (a.command) return copy(a.command, "The command");
  return null;
}

export function planBlock(out, item) {
  const plan = out.plan || {};
  const pid = item.project || (S.route && S.route.pid);
  return h("div", { class: "goal-plan", "data-control": "goal_plan" },
    (plan.gaps || []).map((g) => h("div", { class: "goal-gap" }, h("p", null, icon("alert"), h("b", null, " " + g.what)),
      h("ul", { class: "small" }, (g.options || []).map((o) => h("li", null, o))))),
    h("ol", { class: "goal-steps" }, (plan.steps || []).map((s) => {
      const [label, ic] = STEP_BUTTON[(s.action || {}).kind] || ["Open", "arrow-right"];
      const cmd = (s.action || {}).command;
      return h("li", { class: "goal-step" + (s.available ? "" : " off"), "data-step": s.id },
        h("b", null, s.title), s.detail ? h("p", { class: "small" }, s.detail) : null,
        s.available ? null : h("p", { class: "muted small" }, icon("info"), " Not available yet: " + s.why_not),
        h("div", { class: "btns" },
          s.available ? button(label, { icon: ic, kind: "small", key: "goal:" + s.id, onclick: () => runStep(pid, s) }) : null,
          cmd && (s.action.kind !== "command" || !s.available) ? button("Copy the command", { icon: "copy", kind: "small quiet",
            key: "goal-cmd:" + s.id, onclick: () => copy(cmd, "The command") }) : null));
    })),
    (plan.dropped || []).length ? h("p", { class: "muted small" }, plan.dropped.length + " step(s) the model proposed were not offered: "
      + plan.dropped.map((d) => d.refused).join("; ")) : null);
}

// -- the hand-off dialog -----------------------------------------------------------------------------------

export function openHandoff(pid, opts) {
  const o = opts || {};
  const to = h("select", { id: "ho-to", "data-key": "ho-to", "aria-label": "Which agent" });
  const change = h("input", { id: "ho-change", "data-key": "ho-change", maxlength: "12", placeholder: "C-0004 (optional)", autocomplete: "off" });
  const pre = h("pre", { class: "ho-brief", id: "ho-brief", tabindex: "0", "aria-label": "The brief" }, "Reading the brief…");
  const how = h("div", { class: "ho-how small", id: "ho-how" });
  const acts = h("div", { class: "btns", id: "ho-acts" });
  let data = null;
  const record = async (via) => {
    const out = await api("POST", "/api/projects/" + enc(pid) + "/handoff", Object.assign({ to: to.value, via, change: change.value.trim() }, signed()));
    if (nav.rerender) nav.rerender();     // the Agents strip counts the hand-off
    return out;
  };
  async function load() {
    const q = "?to=" + enc(to.value || o.to || "generic") + (change.value.trim() ? "&change=" + enc(change.value.trim()) : "")
      + "&persona=" + enc(S.persona) + (S.person.trim() ? "&person=" + enc(S.person.trim()) : "");
    try { data = await api("GET", "/api/projects/" + enc(pid) + "/handoff" + q); } catch (e) { pre.textContent = e.message; return; }
    if (to.options.length === 0) {
      Object.entries(data.agents).forEach(([k, label]) => to.append(h("option", { value: k }, label)));
      to.value = o.to && data.agents[o.to] ? o.to : "generic";
    }
    pre.textContent = data.markdown;
    const u = data.use;
    how.replaceChildren(h("p", null, h("b", null, "For " + u.label + ": "), "save it as ", h("code", null, u.prompt_file), ", then ", h("code", null, u.run)),
      h("p", { class: "muted" }, "Rihma's tools for it: ", h("code", null, u.mcp.file), ". " + u.note));
    acts.replaceChildren(
      button("Copy the brief", { icon: "copy", kind: "primary small", key: "ho-copy", onclick: () => act(acts, async () => {
        if (!needPerson()) return;
        await copy(data.markdown, "The brief");
        await record("copy");
      }) }),
      button("Download it", { icon: "download", kind: "small", key: "ho-download", onclick: () => act(acts, async () => {
        if (!needPerson()) return;
        const a = h("a", { href: URL.createObjectURL(new Blob([data.markdown], { type: "text/markdown" })), download: "handoff-" + pid + ".md" });
        document.body.append(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        await record("download");
        say("Downloaded, and the hand-off is on the project's timeline.", "good");
      }) }),
      data.run.available
        ? button("Run it with " + data.run.label, { icon: "play", kind: "small human", key: "ho-run", onclick: () => act(acts, async () => {
          if (!needPerson()) return;
          const out = await record("run");
          closeModal();
          say("Filed " + out.card + ": when a product owner accepts it, the factory's builder cell runs it with " + data.run.label + ", checked after the run.", "good");
        }) })
        : chip("nm", "info", "Run it with a runner: " + data.run.why_not));
  }
  to.addEventListener("change", load);
  change.addEventListener("change", load);
  openModal("Hand off to an agent", h("div", { class: "ho" },
    h("p", { class: "muted small" }, "A brief for a coding agent: the goal, the criteria, the open questions, the plan, the findings, how to run the tests and how to report back. The agent's writes come back as proposals and channel posts."),
    h("div", { class: "ho-row" }, h("label", { for: "ho-to" }, "Agent"), to, h("label", { for: "ho-change" }, "Change"), change),
    pre, how, acts), { icon: "send", wide: true });
  load();
}

export function handoffButton(p) {
  return h("button", { type: "button", class: "btn small", "data-control": "handoff", "data-key": "handoff", "aria-haspopup": "dialog",
    onclick: () => openHandoff(p.meta.id, {}) }, icon("send"), h("span", { class: "lbl" }, "Hand off to an agent"));
}
