/* Shape it in chat (D-0022, kernel/shape.py): a conversation with Rihma beside a draft brief the person can
   edit, then "Create the project from this". Every write is signed with the person and persona; Rihma's
   answer runs beside the request, so the page reads the conversation again until it is in. */

import {
  S, $, $$, h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, empty, pageHead, skeleton,
  openModal, closeModal, segmented, cap, ago, profileOf,
} from "./core.js";
import { pathField } from "./picker.js";

const POLL_MS = 900;
const MAX_UPLOAD = 900 * 1024;   // a file sent from the browser; a larger one is attached by its path
const SH = { dirty: {} };        // the draft fields the person changed and has not saved, per field key

// Enter sends, as in Ask Rihma and the agent channel; Shift+Enter and IME composition stay ordinary editing.
function enterSends(field, send) {
  field.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send.click(); }
  });
}

function modelNote(hasModel) {
  if (hasModel) return null;
  return h("p", { class: "note warning", "data-key": "shape:no-model" }, icon("alert"), h("span", null,
    h("b", null, "No model is set up for Rihma yet. "), "You can start and your words are kept, but Rihma cannot answer until a model is set up. ",
    h("a", { href: "#/models", "data-control": "models_open" }, "Open Models setup"), "."));
}

// A file chosen in the browser, as the attach route takes it: its name and its bytes in base64.
function readFile(file) {
  return new Promise((resolve, reject) => {
    if (file.size > MAX_UPLOAD) { reject(new Error(file.name + " is larger than the browser may send: give its path instead.")); return; }
    const r = new FileReader();
    r.onload = () => resolve({ name: file.name, data_base64: String(r.result).split(",", 2)[1] || "" });
    r.onerror = () => reject(new Error(file.name + " could not be read."));
    r.readAsDataURL(file);
  });
}
async function attachOf(fileInput, pathInput) {
  const file = fileInput.files && fileInput.files[0];
  if (file) return readFile(file);
  const path = pathInput.value.trim();
  return path ? { path } : null;
}
function attachFields(prefix) {
  const file = h("input", { type: "file", id: prefix + "-file", accept: ".md,.txt,.markdown,.csv,.json,.docx,text/*", "aria-label": "Attach a file" });
  const path = h("input", { id: prefix + "-path", maxlength: "2000", autocomplete: "off", spellcheck: "false",
    placeholder: "for example ~/notes/need.md, or a folder", "aria-label": "Or a file or folder path on the cockpit's machine" });
  return { file, path, el: h("div", { class: "shp-attach" },
    h("div", { class: "field" }, h("label", { for: prefix + "-file" }, "A file (text, Markdown or Word)"), file),
    h("div", { class: "field" }, h("label", { for: prefix + "-path" }, "Or a file or folder on the cockpit's machine"),
      pathField(path, { kind: "either", title: "Choose a file or a folder to attach" }))) };
}

// -- the list and a new conversation -----------------------------------------------------------------------

async function renderList(seq) {
  const main = $("#main");
  const data = await api("GET", "/api/shape");
  if (seq !== S.seq) return;
  document.title = "Shape it in chat · Rihmasto.ai";
  const text = h("textarea", { id: "shp-first", rows: "4", maxlength: "8000", "aria-label": "Your first message",
    placeholder: "For example: our support team answers the same questions every day and wants a way to find the answers faster." });
  const att = attachFields("shp-new");
  const start = h("button", { type: "submit", class: "btn primary", "data-control": "shape_start", "data-key": "shape:start" }, icon("message-square"), "Start the conversation");
  const form = h("form", { class: "np-form", novalidate: true },
    h("div", { class: "field" }, h("label", { for: "shp-first" }, "Start with a sentence, a file, or nothing at all"), text),
    att.el, h("div", { class: "btns" }, start, h("span", { class: "muted small" }, "Enter sends · Shift+Enter is a new line. Signed with your name. You choose the profile, mode and maturity when you create the project.")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      const attach = await attachOf(att.file, att.path);
      const out = await api("POST", "/api/shape", Object.assign({ text: text.value.trim(), attach }, signed()));
      location.hash = "#/shape/" + enc(out.shape.id);
    });
  });
  enterSends(text, start);
  const rows = data.conversations.map((c) => h("li", { class: "shp-row", "data-key": "shape:" + c.id },
    h("span", { class: "cat-ic" }, icon(c.state === "created" ? "check-circle" : "message-square")),
    h("div", { class: "sig-b" }, h("a", { href: "#/shape/" + enc(c.id) }, c.title), " ", h("span", { class: "mono muted small" }, c.id),
      h("div", { class: "sig-m" }, h("span", null, "by " + (c.started_by || "?") + " · " + ago(c.started)), h("span", null, c.messages + " messages"))),
    c.state === "created" ? chip("good", "check", "Project " + c.project) : chip("info", "message-square", "Open")));
  fill(main,
    pageHead("Shape it in chat", "Work out what you need with Rihma, in conversation. Rihma asks one or two questions at a time and keeps a draft brief beside the chat, which you can edit.", { icon: "message-square" }),
    modelNote(data.model),
    card({ title: "A new conversation", icon: "plus", id: "shp-new" }, form),
    card({ title: "Conversations", icon: "comment", id: "shp-list" },
      rows.length ? h("ul", { class: "emb-list" }, rows) : empty("message-square", "No conversation yet.")));
}

// -- one conversation ----------------------------------------------------------------------------------

function messageEl(m) {
  const mine = m.from === "person";
  return h("li", { class: "shp-msg " + (mine ? "person" : "rihma") + (m.note ? " " + m.note : "") },
    h("span", { class: "shp-who" }, mine ? (m.person || "You") : "Rihma"),
    h("p", null, m.text),
    m.link ? h("a", { href: m.link, class: "btn small", "data-control": "models_open" }, icon("cpu"), h("span", { class: "lbl" }, "Open Models setup")) : null);
}

function fieldEl(f, conv, open) {
  const id = "shp-f-" + f.key;
  const value = conv.draft[f.key];
  const text = f.list ? (value || []).join("\n") : (value || "");
  const input = f.key === "title"
    ? h("input", { id, maxlength: "200", value: text, disabled: !open || null })
    : h("textarea", { id, rows: f.list ? "3" : "2", disabled: !open || null }, text);
  input.dataset.field = f.key;
  if (f.list) input.dataset.list = "1";
  input.addEventListener("input", () => { SH.dirty[f.key] = true; });
  const yours = (conv.edited || {})[f.key];
  return h("div", { class: "field shp-field" + (yours ? " yours" : "") },
    h("label", { for: id }, f.label, f.list ? h("small", { class: "muted" }, " one per line") : null,
      yours ? chip("accent", "user", "yours", { tip: "You edited it: Rihma leaves it as you wrote it." }) : null), input);
}

function readiness(conv) {
  if (conv.state === "created") return null;
  return h("div", { class: "shp-ready", role: "status" },
    conv.good_enough ? chip("good", "check-circle", "Good enough to create the project") : chip("warning", "alert", "Still needed: " + conv.missing.join(", ")),
    conv.ready_why ? h("p", { class: "muted small" }, "Rihma: " + conv.ready_why) : null);
}

function openCreate(conv) {
  const s = conv.suggestion;
  const profiles = (S.meta && S.meta.profiles) || [];
  const profile = h("select", { id: "shp-profile", "aria-label": "Work profile" },
    profiles.map((p) => h("option", { value: p.id, selected: p.id === s.profile }, p.label)));
  const maturity = segmented("shp-maturity", Object.keys(S.meta.maturities).map((m) => [m, cap(m)]), s.maturity, () => {}, { label: "Maturity" });
  const mode = segmented("shp-mode", Object.keys(S.meta.modes).map((m) => [m, cap(m)]), s.mode, () => {}, { label: "Mode" });
  const val = (seg) => (seg.querySelector('[aria-checked="true"]') || {}).dataset.key.split(":")[1];
  const submit = h("button", { type: "submit", class: "btn primary", "data-control": "shape_create", "data-key": "shape:create-confirm" }, icon("plus"), "Create and start the intake");
  const form = h("form", { class: "np-form", novalidate: true },
    h("p", { class: "note" }, icon("sparkles"), h("span", null, h("b", null, "Rihma suggests "), profileOf(s.profile).label + ", " + s.mode + ", " + s.maturity + ": " + s.why + ".")),
    h("div", { class: "field" }, h("label", { for: "shp-profile" }, "Work profile"), profile),
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", null, "Maturity"), maturity), h("div", { class: "field" }, h("label", null, "Mode"), mode)),
    h("p", { class: "muted small" }, "The draft becomes the project's request: what it says is never asked again at intake."),
    h("div", { class: "btns" }, submit));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      const out = await api("POST", "/api/shape/" + enc(conv.id) + "/create", Object.assign({ profile: profile.value, maturity: val(maturity), mode: val(mode) }, signed()));
      closeModal();
      say("Project " + out.project.id + " is created from the conversation. Its intake runs as job " + out.job.id + ".", "good");
      S.jumped = true;
      location.hash = "#/p/" + enc(out.project.id) + "/overview";
    });
  });
  openModal("Create the project from this", form, { icon: "plus", wide: true });
}

function draftValues(box) {
  const out = {};
  $$("[data-field]", box).forEach((el) => {
    if (!SH.dirty[el.dataset.field]) return;
    out[el.dataset.field] = el.dataset.list ?el.value.split("\n").map((x) => x.trim()).filter(Boolean) : el.value.trim();
  });
  return out;
}

function paint(conv, hasModel) {
  const open = conv.state === "open";
  const log = $("#shp-log");
  if (!log) return;
  fill(log, conv.messages.map(messageEl), conv.pending ? h("li", { class: "shp-msg rihma pending" }, h("span", { class: "shp-who" }, "Rihma"),
    h("p", { class: "muted" }, icon("clock"), " Rihma is thinking…")) : null);
  log.scrollTop = log.scrollHeight;
  fill($("#shp-model"), modelNote(hasModel));
  const box = $("#shp-draft");
  const keep = {};
  $$("[data-field]", box).forEach((el) => { if (SH.dirty[el.dataset.field]) keep[el.dataset.field] = el.value; });
  const focused = box.contains(document.activeElement) ? document.activeElement.dataset.field : null;
  fill(box, conv.fields.map((f) => fieldEl(f, conv, open)));
  for (const [k, v] of Object.entries(keep)) { const el = box.querySelector('[data-field="' + k + '"]'); if (el) el.value = v; }
  if (focused) { const el = box.querySelector('[data-field="' + focused + '"]'); if (el) el.focus(); }
  fill($("#shp-state"), readiness(conv), conv.state === "created" ? h("p", { class: "note" }, icon("check-circle"),
    h("span", null, "This conversation became project ", h("a", { href: "#/p/" + enc(conv.project) + "/overview" }, conv.project), ".")) : null);
  $$("#shp-chat button, #shp-chat textarea, #shp-chat input, #shp-actions button").forEach((el) => {
    el.disabled = !open || (conv.pending && el.dataset.key !== "shape:attach-toggle") || null;
  });
}

async function poll(id, seq) {
  if (seq !== S.seq) return;
  const out = await api("GET", "/api/shape/" + enc(id)).catch(() => null);
  if (!out || seq !== S.seq) return;
  paint(out.shape, out.model);
  if (out.shape.pending) S.timer = setTimeout(() => poll(id, seq), POLL_MS);
}

function chatCard(id, seq) {
  const input = h("textarea", { id: "shp-input", rows: "3", maxlength: "8000", "aria-label": "Your message", placeholder: "Answer Rihma, or tell it more" });
  const send = h("button", { type: "submit", class: "btn primary", "data-control": "shape_say", "data-key": "shape:say" }, icon("send"), "Send");
  const att = attachFields("shp-att");
  att.el.hidden = true;
  const doAttach = button("Attach it", { icon: "upload", kind: "small", "data-control": "shape_attach", key: "shape:attach" });
  const toggle = button("Attach a file or folder", { icon: "upload", kind: "small", key: "shape:attach-toggle", expanded: "false", controls: "shp-attach-box" });
  att.el.id = "shp-attach-box";
  att.el.append(h("div", { class: "btns" }, doAttach));
  toggle.addEventListener("click", () => { att.el.hidden = !att.el.hidden; toggle.setAttribute("aria-expanded", String(!att.el.hidden)); });
  const after = (out) => {
    paint(out.shape, out.model);
    if (out.shape.pending) S.timer = setTimeout(() => poll(id, seq), POLL_MS);
  };
  const form = h("form", { class: "shp-form", novalidate: true }, h("label", { class: "vh", for: "shp-input" }, "Your message"), input,
    h("div", { class: "btns" }, send, toggle, h("span", { class: "muted small" }, "Enter sends · Shift+Enter is a new line")), att.el);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!input.value.trim() || !needPerson()) { if (!input.value.trim()) input.focus(); return; }
    act(form, async () => {
      const out = await api("POST", "/api/shape/" + enc(id) + "/say", Object.assign({ text: input.value.trim() }, signed()));
      input.value = "";
      after(out);
      input.focus();
    });
  });
  enterSends(input, send);
  doAttach.addEventListener("click", () => {
    if (!needPerson()) return;
    act(form, async () => {
      const attach = await attachOf(att.file, att.path);
      if (!attach) { say("Choose a file, or give a path.", "warning"); return; }
      const out = await api("POST", "/api/shape/" + enc(id) + "/attach", Object.assign({ attach }, signed()));
      att.file.value = "";
      att.path.value = "";
      att.el.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      after(out);
    });
  });
  return card({ title: "Chat with Rihma", icon: "message-square", id: "shp-chat", cls: "shp-chat" },
    h("div", { id: "shp-model" }), h("ol", { id: "shp-log", class: "shp-log", role: "log", "aria-live": "polite", "aria-label": "The conversation", tabindex: "0" }), form);
}

function draftCard(conv) {
  const save = button("Save the draft", { icon: "check", kind: "small primary", "data-control": "shape_draft", key: "shape:draft" });
  const create = button("Create the project from this", { icon: "plus", kind: "primary", "data-control": "shape_create", key: "shape:create" });
  save.addEventListener("click", () => {
    if (!needPerson()) return;
    const changes = draftValues($("#shp-draft"));
    if (!Object.keys(changes).length) { say("Nothing in the draft changed.", "info"); return; }
    act($("#shp-actions"), async () => {
      const out = await api("PUT", "/api/shape/" + enc(conv.id) + "/draft", Object.assign({ draft: changes }, signed()));
      SH.dirty = {};
      paint(out.shape, out.model);
      say("The draft is saved. Rihma leaves the fields you edited as you wrote them.", "good");
    });
  });
  create.addEventListener("click", async () => {
    const out = await api("GET", "/api/shape/" + enc(conv.id)).catch((e) => { say(e.message, "critical"); return null; });
    if (out) openCreate(out.shape);
  });
  return card({ title: "Draft brief", icon: "file-check", id: "shp-draft-card", cls: "shp-draft-card",
    info: "What Rihma understood so far, in fields you can edit. It becomes the project's request when you create the project." },
  h("div", { id: "shp-draft" }), h("div", { id: "shp-state" }), h("div", { class: "btns", id: "shp-actions" }, save, create));
}

async function renderOne(id, seq) {
  const main = $("#main");
  const out = await api("GET", "/api/shape/" + enc(id));
  if (seq !== S.seq) return;
  const conv = out.shape;
  SH.dirty = {};
  document.title = conv.title + " · Shape it in chat · Rihmasto.ai";
  fill(main,
    pageHead(conv.title, conv.id + " · started by " + (conv.started_by || "?") + " " + ago(conv.started), {
      icon: "message-square", actions: [h("a", { href: "#/shape", class: "btn quiet" }, icon("chevron-left"), h("span", { class: "lbl" }, "All conversations"))] }),
    h("div", { class: "shp-cols" }, chatCard(id, seq), draftCard(conv)));
  paint(conv, out.model);
  if (conv.pending) S.timer = setTimeout(() => poll(id, seq), POLL_MS);
}

export async function renderShape(seq) {
  const main = $("#main");
  const done = skeleton(main, "the conversation");
  try {
    if (S.route && S.route.id) await renderOne(S.route.id, seq);
    else await renderList(seq);
  } finally { done(); }
}
