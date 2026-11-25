/* Choose a folder or a file by browsing (FR-PICK1, kernel/pick.py, docs/guides/inputs.md).

   Every field that takes a path on the cockpit's machine is a path field: type or paste as before, or
   - Browse…: the computer's own folder dialog, when this browser runs on the cockpit's machine for a single
     operator (POST /api/pick/native); anywhere else, the folder browser below. While it is open the page names
     the computer it opened on and offers Browse here instead (a page through an SSH tunnel looks local); a
     field that takes a file or a folder has File… and Folder… instead;
   - Browse here: the folder browser in the page, always: the places to start from (recent folders, the roots,
     the home folder, the drives), a breadcrumb, the folders (and files) with git and project badges, a filter
     (searched in the whole folder when it holds more than the rows shown),
     the keyboard (arrows, Enter, Backspace), and Choose. At phone width it is a full-screen sheet.
   A folder dropped on the field gives only its name (browsers do not give the full path), so the field says so.
   What is chosen is checked again where it is used; a folder outside the allowed ones offers Allow it. */

import { S, h, fill, icon, chip, api, say, signed, needPerson, iconButton, enc, AuthError } from "./core.js";

const P = { places: null, native: null, enforced: false, at: 0 };
const TTL = 30000;
const PLACE_ICON = { recent: "clock", root: "folder", home: "home", drive: "server" };
const n = (x) => Number(x || 0).toLocaleString("en");

function who() { return "person=" + encodeURIComponent(S.person.trim()) + "&persona=" + encodeURIComponent(S.persona); }

async function places(fresh) {
  if (fresh || !P.places || Date.now() - P.at > TTL) {
    const out = await api("GET", "/api/pick/places?" + who());
    Object.assign(P, { places: out.places, native: out.native, enforced: out.enforced, at: Date.now() });
  }
  return P;
}

function looksLikePath(t) { return /^([A-Za-z]:[\\/]|\\\\|\/|~)/.test(String(t || "").trim()) && !/[\r\n]/.test(t); }
function parentOf(p) { const m = /^(.*)[\\/][^\\/]+$/.exec(p); return m ? (m[1] || "/").replace(/^([A-Za-z]:)$/, "$1\\") : p; }
function words(kind) { return kind === "file" ? "a file" : kind === "either" ? "a file or a folder" : "a folder"; }

function remember(path) {
  if (!S.person.trim()) return;
  api("POST", "/api/pick/recent", Object.assign({ path }, signed())).then(() => { P.at = 0; }).catch(() => null);
}

// -- Browse…: the computer's own dialog, or the folder browser -----------------------------------------------

// While the dialog is open the page names the computer it opened on and offers Browse here instead: a page
// reached through an SSH tunnel looks like the cockpit's own, so the dialog may be where nobody sits. Instead
// closes that dialog (POST /api/pick/native/cancel) and opens the folder browser; Escape closes it and stops.
// It is a modal of its own, so it stays usable above a dialog the field sits in.
function waiting(host) {
  const box = h("dialog", { class: "pick-wait", "aria-label": "The folder dialog is open" });
  const instead = new Promise((resolve) => {
    const stop = (out) => { api("POST", "/api/pick/native/cancel", signed()).catch(() => null); resolve(out); };
    const btn = h("button", { type: "button", class: "btn small primary pick-instead" }, icon("search"), h("span", { class: "lbl" }, "Browse here instead"));
    btn.addEventListener("click", () => stop({ instead: true }));
    box.addEventListener("cancel", (e) => { e.preventDefault(); stop({ cancelled: true }); });
    fill(box, icon("folder"), h("span", null, "The folder dialog is open on " + (host || "the cockpit's computer") + ": choose there. "
      + "Not sitting at that computer (say, the page came through an SSH tunnel)?"), btn);
  });
  document.body.append(box);
  box.showModal();
  return { box, instead };
}

export async function browse(o, nativeKind) {
  if (!needPerson()) return null;
  const pl = await places().catch(() => P);
  if (!pl.native || !pl.native.available) return browseHere(o);
  const kind = nativeKind || (o.kind === "file" ? "file" : "folder");
  const wait = waiting(pl.native.host);
  try {
    const call = api("POST", "/api/pick/native", Object.assign({ kind,
      title: o.title || "Choose " + words(kind), start: looksLikePath(o.start) ? o.start : "" }, signed()));
    call.catch(() => null);
    const out = await Promise.race([call, wait.instead]);
    if (out.instead) return browseHere(o);
    if (out.cancelled) { say("Nothing was chosen.", "info"); return null; }
    const got = out.picked;
    if (!got.readable && o.purpose !== "allow") say(got.path + " " + got.why + (got.offer ? " (" + got.offer.say + " in Settings > Folders)." : "."), "warning");
    if (got.readable) remember(got.kind === "file" ? parentOf(got.path) : got.path);
    return got.path;
  } catch (e) {
    if (e instanceof AuthError) return null;
    if (e.status === 409 || e.status === 501) { P.at = 0; say(e.message, "info"); return browseHere(o); }
    throw e;
  } finally { if (wait.box.open) wait.box.close(); wait.box.remove(); }
}

// -- Browse here: the folder browser in the page -------------------------------------------------------------

function badge(row) {
  const out = [];
  if (row.git) out.push(chip("accent", "merge", "git"));
  if (row.project) out.push(chip("good", "check", (row.project.how === "attached" ? "attached: " : "adopted: ") + row.project.title));
  if (row.never) out.push(chip("critical", "shield", "never read"));
  else if (row.link && !row.readable) out.push(chip("warning", "link", "link, not followed"));
  else if (row.readable === false) out.push(chip("neutral", "shield", "not allowed yet"));
  return out;
}

function optionWords(row, isFile) {
  return row.name + (isFile ? ", file" : ", folder") + (row.git ? ", git repository" : "")
    + (row.project ? ", already the project " + row.project.title : "") + (row.readable === false ? ", " + (row.never ? "never read" : "not allowed yet") : "");
}

function rowEl(row, isFile, on) {
  const li = h("li", { role: "option", tabindex: "-1", class: "pick-row" + (row.readable === false ? " off" : ""), "aria-selected": "false",
    "aria-label": optionWords(row, isFile), "data-path": row.path, title: row.why || row.path },
  icon(isFile ? "file-check" : "folder"), h("span", { class: "pick-name" }, row.name),
  h("span", { class: "pick-badges" }, badge(row)),
  row.modified ? h("small", { class: "pick-at muted" }, row.modified.slice(0, 10)) : null);
  li.addEventListener("click", () => on.pick(row, isFile, li));
  li.addEventListener("dblclick", () => { if (isFile) on.choose(); });
  return li;
}

function allowBlock(folder, on) {
  const off = folder.offer;
  if (!off) return null;
  if (off.who !== "you") return h("p", { class: "small" }, off.say + ": IT allows a folder in Settings > Folders the cockpit may read.");
  const box = h("div", { class: "btns pick-allow" });
  const ask = h("button", { type: "button", class: "btn small", "data-control": "pick_allow" }, icon("folder"), h("span", { class: "lbl" }, off.say));
  ask.addEventListener("click", () => {
    const yes = h("button", { type: "button", class: "btn small primary" }, icon("check"), h("span", { class: "lbl" }, "Yes, allow " + off.root));
    yes.addEventListener("click", async () => {
      if (!needPerson()) return;
      yes.disabled = true;
      try {
        await api("POST", "/api/source/roots", Object.assign({ folder: off.root, confirm: true }, signed()));
        say(off.root + " is allowed: the cockpit may read the folders under it. Recorded in the factory's ledger.", "good");
        P.at = 0;
        await on.reload();
      } catch (e) { if (!(e instanceof AuthError)) say(e.message, "critical"); yes.disabled = false; }
    });
    fill(box, h("span", { class: "small" }, "The cockpit may then read every folder under " + off.root + ". Allow it?"), yes,
      h("button", { type: "button", class: "btn small", onclick: () => fill(box, ask) }, h("span", { class: "lbl" }, "Not now")));
    yes.focus();
  });
  fill(box, ask);
  return box;
}

function placesEl(pl, on) {
  return h("nav", { class: "pick-places", "aria-label": "Places" }, h("ul", { class: "plain" }, (pl.places || []).map((p) =>
    h("li", null, h("button", { type: "button", class: "pick-place" + (p.readable ? "" : " off"), "data-path": p.path, title: p.why || p.path,
      "aria-label": (p.kind === "recent" ? "Recent: " : "") + p.label + (p.readable ? "" : ", not allowed yet"), onclick: (e) => on.go(p.path, e.detail === 0) },
    icon(PLACE_ICON[p.kind] || "folder"), h("span", null, p.label))))));
}

function trail(folder, on) {
  return h("nav", { class: "pick-crumbs", "aria-label": "Folder path" }, h("ol", null, folder.crumbs.map((c, i) =>
    h("li", null, i === folder.crumbs.length - 1 ? h("span", { "aria-current": "location", class: "mono" }, c.name)
      : h("button", { type: "button", class: "pick-crumb mono", onclick: (e) => on.go(c.path, e.detail === 0) }, c.name)))));
}

function keys(list, on) {
  list.addEventListener("keydown", (e) => {
    const all = [...list.querySelectorAll('[role="option"]')];
    const i = all.indexOf(document.activeElement);
    const move = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: all.length - 1 }[e.key];
    if (move !== undefined && all.length) { e.preventDefault(); on.focus(all[Math.max(0, Math.min(all.length - 1, move))]); return; }
    // a folder opened (or left) from the keyboard keeps the focus in the list
    if ((e.key === "Enter" || e.key === "ArrowRight") && i >= 0) { e.preventDefault(); on.keyed(!all[i].dataset.file); all[i].click(); if (e.key === "Enter" && all[i].dataset.file) on.choose(); return; }
    if (e.key === "Backspace" || e.key === "ArrowLeft") { e.preventDefault(); on.up(true); }
  });
}

export function browseHere(o) {
  const kind = o.kind || "folder";
  return new Promise((resolve) => {
    const st = { folder: null, file: null, q: "", hidden: false, done: false, kbd: false, capped: false, timer: 0 };
    const title = h("h2", { id: "pick-h" }, o.title || "Choose " + words(kind));
    const placesBox = h("div", { class: "pick-side" });
    const crumbBox = h("div", { class: "pick-trail" });
    const up = iconButton("chevron-left", "Up one folder", () => on.up(), { "data-control": "pick_up" });
    const q = h("input", { type: "search", class: "pick-q", placeholder: "Filter this folder", "aria-label": "Filter this folder", autocomplete: "off", spellcheck: "false" });
    const state = h("div", { class: "pick-state small", role: "status", "aria-live": "polite" });
    const list = h("ul", { class: "pick-list", role: "listbox", "aria-label": "Folders", "data-control": "pick_list", tabindex: "-1" });
    const more = h("div", { class: "pick-more small muted" });
    const sel = h("span", { class: "pick-sel mono" });
    const chooseBtn = h("button", { type: "button", class: "btn primary", "data-control": "pick_choose" }, icon("check"), h("span", { class: "lbl" }, "Choose this folder"));
    const cancel = h("button", { type: "button", class: "btn" }, h("span", { class: "lbl" }, "Cancel"));
    const dlg = h("dialog", { class: "pick-dlg", "aria-labelledby": "pick-h", "data-kind": kind },
      h("div", { class: "pick-in" },
        h("div", { class: "pick-head" }, h("span", { class: "modal-ic" }, icon("folder")), title, iconButton("x", "Close", () => finish(null))),
        h("div", { class: "pick-body" }, placesBox,
          h("div", { class: "pick-main" }, h("div", { class: "pick-bar" }, up, crumbBox), q, state, list, more)),
        h("div", { class: "pick-foot" }, sel, h("div", { class: "btns" }, cancel, chooseBtn))));

    function finish(path) {
      if (st.done) return;
      st.done = true;
      if (dlg.open) dlg.close();
      dlg.remove();
      if (path) remember(st.file ? parentOf(path) : path);
      resolve(path);
    }
    const on = {
      go: (p, kb) => { st.kbd = !!kb; load(p); },
      up: (kb) => { if (st.folder && st.folder.parent) on.go(st.folder.parent, kb); },
      keyed: (yes) => { st.kbd = !!yes; },
      reload: () => load(st.folder ? st.folder.path : null, true),
      choose: () => choose(),
      focus: (el) => {
        list.querySelectorAll('[role="option"]').forEach((x) => { x.tabIndex = -1; x.setAttribute("aria-selected", "false"); });
        el.tabIndex = 0; el.setAttribute("aria-selected", "true"); el.focus();
      },
      pick: (row, isFile, li) => {
        on.focus(li);
        if (isFile) { st.file = row; foot(); return; }
        if (row.never || (row.link && !row.readable)) { st.kbd = false; say(row.name + ": " + row.why + ".", "warning"); return; }
        on.go(row.path, st.kbd);
      },
    };
    function choosable() {
      const f = st.folder;
      if (!f) return null;
      if (st.file && kind !== "folder") return st.file.path;
      if (kind === "file") return null;
      return f.readable || o.purpose === "allow" ? f.path : null;
    }
    function foot() {
      const path = choosable();
      fill(sel, path || (st.folder ? st.folder.path : ""));
      fill(chooseBtn, icon("check"), h("span", { class: "lbl" }, st.file && kind !== "folder" ? "Choose this file" : kind === "file" ? "Choose a file" : "Choose this folder"));
      chooseBtn.disabled = !path;
    }
    function choose() { const p = choosable(); if (p) finish(p); }
    function draw() {
      const f = st.folder;
      const text = st.q.trim().toLowerCase();
      const hit = (r) => !text || r.name.toLowerCase().includes(text);
      const folders = f.folders.concat(st.hidden ? f.hidden : []).filter(hit);
      const files = (f.files || []).filter(hit);
      list.setAttribute("aria-label", "In " + f.name);
      fill(list, folders.map((r) => rowEl(r, false, on)), files.map((r) => { const li = rowEl(r, true, on); li.dataset.file = "1"; return li; }));
      const searching = text && st.capped && (f.q || "").toLowerCase() !== text;
      if (!folders.length && !files.length) fill(list, h("li", { class: "pick-empty muted small", role: "option", "aria-disabled": "true" }, searching ? "Searching all of " + f.name + "…" : text ? "Nothing here matches “" + st.q + "”." : "No folders here."));
      const first = list.querySelector('[role="option"]:not([aria-disabled])');
      if (first) first.tabIndex = 0;
      const notes = [];
      if (f.more || f.files_more) notes.push(n(f.more + f.files_more) + (f.q ? " more match: type more of the name." : " more not shown: type in the filter to search all of them."));
      if (!f.files_listed && kind !== "folder") notes.push("Files are listed only in the folders the cockpit may read.");
      fill(more, notes.map((x) => h("p", null, x)),
        f.hidden.length ? h("button", { type: "button", class: "btn small quiet", "data-control": "pick_hidden", "aria-pressed": String(st.hidden),
          onclick: () => { st.hidden = !st.hidden; draw(); } }, icon("eye"), h("span", { class: "lbl" }, (st.hidden ? "Fold " : "Show ") + n(f.hidden.length) + " hidden or tool folders")) : null);
    }
    const listUrl = (path) => "/api/pick/list?" + who() + "&files=" + (kind === "folder" ? "0" : "1") + (path ? "&path=" + encodeURIComponent(path) : "");
    function focusList() {
      const first = list.querySelector('[role="option"]:not([aria-disabled])');
      if (first) on.focus(first); else list.focus();
    }
    // A folder longer than the rows shown: the filter is searched in the whole folder, on the server.
    async function search() {
      const f = st.folder;
      const text = st.q.trim();
      if (!f) return;
      try {
        const out = await api("GET", listUrl(f.path) + "&q=" + encodeURIComponent(text));
        if (st.done || st.folder !== f || st.q.trim() !== text) return;          // moved on, or typed on
        st.folder = out.folder;
        draw();
        foot();
      } catch (e) { if (!(e instanceof AuthError)) fill(state, h("p", { class: "pick-err", role: "alert" }, e.message)); }
    }
    async function load(path, fresh) {
      const kb = st.kbd;
      st.kbd = false;
      fill(state, "Reading the folder…");
      try {
        const out = await api("GET", listUrl(path));
        st.folder = out.folder;
        st.capped = out.folder.more + out.folder.files_more + out.folder.hidden_more > 0;
        st.file = null;
        if (!fresh) { st.q = ""; q.value = ""; }
        if (fresh) fill(placesBox, placesEl(await places(true), on));
      } catch (e) {
        if (e instanceof AuthError) { finish(null); return; }
        fill(state, h("p", { class: "pick-err", role: "alert" }, e.message));
        return;
      }
      const f = st.folder;
      fill(crumbBox, trail(f, on));
      up.disabled = !f.parent;
      fill(state, f.readable ? h("span", null, icon("check-circle"), " The cockpit may read this folder" + (f.git ? ": a git repository." : ".")) : h("div", null,
        h("p", null, icon("shield"), " " + f.name + " " + f.why + (f.folders.length ? ". Its folders are shown by name only." : ".")), allowBlock(f, on)),
      f.project ? h("p", null, "Already a project here: ", h("a", { href: "#/p/" + enc(f.project.project) + "/overview", onclick: () => finish(null) }, f.project.title), ".") : null);
      draw();
      foot();
      if (kb) focusList();
      if (fresh && st.capped && st.q.trim()) search();
    }
    q.addEventListener("input", () => {
      st.q = q.value;
      draw();
      if (st.capped) { clearTimeout(st.timer); st.timer = setTimeout(search, 200); }
    });
    q.addEventListener("keydown", (e) => { if (e.key === "ArrowDown") { const first = list.querySelector('[role="option"]:not([aria-disabled])'); if (first) { e.preventDefault(); on.focus(first); } } });
    keys(list, on);
    chooseBtn.addEventListener("click", choose);
    cancel.addEventListener("click", () => finish(null));
    dlg.addEventListener("close", () => finish(null));
    document.body.append(dlg);
    dlg.showModal();
    places().then((pl) => fill(placesBox, placesEl(pl, on))).catch(() => null);
    load(looksLikePath(o.start) ? o.start : null).then(() => q.focus());
  });
}

// -- the field ------------------------------------------------------------------------------------------------

// Browse… opens the computer's own dialog, which picks either a folder or a file: a field that takes either has
// File… and Folder…, so a file such as need.md can be chosen there too.
function nativeButtons(o, label, run) {
  const kinds = o.kind === "either" ? ["file", "folder"] : [o.kind === "file" ? "file" : "folder"];
  return kinds.map((k) => {
    const two = kinds.length > 1;
    const b = h("button", { type: "button", class: "btn small", "data-control": "pick_browse", "data-kind": k, "aria-label": "Browse for " + (two ? words(k) : label),
      tip: "Opens this computer's own " + (k === "file" ? "file" : "folder") + " dialog when you sit at the cockpit's machine; elsewhere the folder browser" },
    icon(k === "file" ? "file-check" : "folder"), h("span", { class: "lbl" }, two ? (k === "file" ? "File…" : "Folder…") : "Browse…"));
    b.addEventListener("click", () => run((x) => browse(x, k), b));
    return b;
  });
}

export function pathField(input, opts) {
  const o = opts || {};
  const take = (path) => {
    if (!path) return;
    input.value = path;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    if (o.onPick) o.onPick(path);
  };
  const ask = () => ({ kind: o.kind || "folder", title: o.title, purpose: o.purpose, start: o.start ? o.start() : input.value.trim() });
  // after choosing (or not), the focus goes back to the field, or to the button when the field is hidden
  const back = (btn) => { const el = input.type !== "hidden" && input.isConnected ? input : btn; if (el.isConnected) el.focus(); };
  const run = (fn, btn) => fn(ask()).then((path) => { take(path); back(btn); }).catch((e) => { if (!(e instanceof AuthError)) say(e.message, "critical"); });
  const label = o.name || words(o.kind);
  const here = h("button", { type: "button", class: "btn small quiet", "data-control": "pick_here", "aria-label": "Browse here for " + label,
    tip: "Browse the cockpit's folders here in the page" }, icon("search"), h("span", { class: "lbl" }, "Browse here"));
  here.addEventListener("click", () => { if (needPerson()) run(browseHere, here); });
  const note = h("small", { class: "pick-note muted", "aria-live": "polite" });
  const box = h("div", { class: "pick-field" }, h("div", { class: "pick-row-in" }, input, h("div", { class: "btns pick-btns" }, nativeButtons(o, label, run), here)), note);
  box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("drop"); });
  box.addEventListener("dragleave", () => box.classList.remove("drop"));
  box.addEventListener("drop", (e) => {
    e.preventDefault();
    box.classList.remove("drop");
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (!f) return;
    input.value = f.name;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    fill(note, "Browsers give only the name of a dropped " + (f.type ? "file" : "folder") + " (" + f.name + "), not where it is: use Browse… to choose it.");
  });
  return box;
}

// Browse buttons beside a field that is not a one-line path (a need that may be a folder, the chat's answer box):
// the chosen path goes to ``onPick``; ``start`` names where browsing starts.
export function browseButtons(opts) {
  const box = pathField(h("input", { type: "hidden" }), opts);
  box.classList.add("pick-only");
  return box;
}
