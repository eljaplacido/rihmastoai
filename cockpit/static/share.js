/* Share (FR-SHR1): observer links, a time-limited read-only view of your work for a colleague.

   Make a link for one project or every project (the platform scope), for an hour, a day or a week, optionally
   naming the guest; a confidential project only with its own explicit tick. The address is shown once, here, to
   copy and pass on yourself: Rihmasto sends nothing. Below: each link with who is watching now, when it was last
   opened and Revoke; whether guests follow the view you are on (with a pause); the guests' comments; and their
   suggested answers to intake questions, which you confirm (signed by you) or decline. */

import { S, h, fill, icon, chip, button, api, enc, card, pageHead, plural, act, say, needPerson, signed, local } from "./core.js";
import { pick, datum, emptyState, localDateTime } from "./words.js";
import { followPaused, setFollowPaused, followNow } from "./observe_follow.js";

const HOURS = [[1, "An hour"], [24, "A day"], [168, "A week"]];

function field(label, control) { return h("label", { class: "sh-field" }, h("span", { class: "sh-lbl" }, label), control); }

function copyOnce(out) {
  const b = button("Copy the link", { icon: "copy", kind: "small", "data-control": "observe_link_copy" });
  b.addEventListener("click", () => {
    const manual = () => say("Select the address and copy it.", "warning");
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(out.url).then(() => say("Copied. Pass it on yourself.", "good"), manual);
    else manual();
  });
  return h("div", { class: "sh-once", role: "status", "data-once": "" },
    h("p", null, h("b", null, "Shown once: "), "copy this link now and pass it on yourself. It is not shown again."),
    h("p", { class: "small", "data-ud": "" }, out.said),
    h("p", { class: "mono small sh-url", "data-ud": "" }, out.url), b,
    h("p", { class: "small muted" }, pick("Your colleague opens it on this computer. From elsewhere they need an ssh tunnel, which is a login on this machine: far more than read only. Never give them your own login; the guide shows a restricted account for one port.",
      "The guest opens it on this machine, or through ssh -L <port>:127.0.0.1:<port> <host>. A tunnel is an ssh login: far more than read only, so only from a restricted account (restrict,port-forwarding,permitopen) as docs/guides/observer-links.md shows.")));
}

function makeForm(d, redraw) {
  const projects = d.projects || [];
  const scope = h("select", { id: "sh-scope", "aria-label": "What to share" },
    h("option", { value: "project" }, "One project"), h("option", { value: "platform" }, "Every project (platform)"));
  const project = h("select", { id: "sh-project", "aria-label": "Project" },
    projects.map((p) => h("option", { value: p.pid }, p.title + (p.confidential ? " (confidential)" : ""))));
  const pre = (S.route && S.route.pid) || local.get("gf.share.project");
  if (pre && projects.some((p) => p.pid === pre)) project.value = pre;
  let hours = 1;
  const seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "For how long" });
  const drawSeg = () => fill(seg, HOURS.map(([v, l]) => h("button", { type: "button", role: "radio", class: "seg-b",
    "aria-checked": String(v === hours), "data-key": "share-hours:" + v, onclick: () => { hours = v; drawSeg(); } }, h("span", { class: "lbl" }, l))));
  drawSeg();
  const guest = h("input", { id: "sh-guest", type: "text", maxlength: "80", placeholder: "Maria Example (optional)", autocomplete: "off" });
  const conf = h("input", { type: "checkbox", id: "sh-conf" });
  const intake = h("input", { type: "checkbox", id: "sh-intake" });
  const scopeNote = h("p", { class: "small muted sh-scope-note", "data-ud": "" });
  const sync = () => {
    const every = scope.value === "platform";
    project.disabled = every || !projects.length;
    intake.disabled = every;
    if (every) intake.checked = false;
    const chosen = projects.find((p) => p.pid === project.value);
    scopeNote.textContent = every
      ? "Platform-wide: every project you see" + (conf.checked ? ", confidential ones too." : ". Confidential projects are left out unless you tick them.")
      : "This project only" + (chosen && chosen.confidential ? ": it is confidential, so it is shared only with the tick below." : ".");
  };
  [scope, project, conf].forEach((x) => x.addEventListener("change", sync));
  sync();
  const out = h("div", { class: "sh-out" });
  const go = button("Make the link", { kind: "primary human", icon: "link", "data-control": "observe_link", key: "share:make" });
  go.addEventListener("click", () => {
    if (!needPerson()) return;
    const every = scope.value === "platform";
    if (!every && !project.value) { say("Choose a project to share, or share every project.", "warning"); return; }
    const body = Object.assign({ scope: scope.value, hours, guest: guest.value.trim(), confidential: conf.checked,
      intake: intake.checked }, every ? {} : { project: project.value }, signed());
    act(go.parentNode, async () => {
      const made = await api("POST", "/api/observe/links", body);
      if (!every) local.set("gf.share.project", project.value);
      fill(out, copyOnce(made));
      followNow();
      redraw(false);
    });
  });
  return card({ title: "Make an observer link", icon: "eye", id: "sh-make",
    info: "A read-only view of your work: your colleague watches, comments, and never decides, runs or changes anything." },
  h("div", { class: "sh-grid" }, field("What to share", scope), field("Project", project), field("For how long", seg), field("Guest's name", guest)),
  scopeNote,
  h("label", { class: "sh-check" }, conf, " Include confidential projects (explicit: never shown otherwise)"),
  h("label", { class: "sh-check" }, intake, " Define the project together: they may suggest answers to the intake questions, for you to confirm"),
  h("div", { class: "btns" }, go), out);
}

function followCard() {
  const paused = followPaused();
  const b = button(paused ? "Show guests the view I am on" : "Pause: hide the view I am on", { kind: "small", icon: paused ? "eye" : "pause",
    "data-control": "observe_presence", key: "share:follow" });
  b.addEventListener("click", () => {
    if (!needPerson()) return;
    setFollowPaused(!paused);
    b.closest(".card").replaceWith(followCard());
    say(paused ? "Guests may follow the view you are on again." : "Paused: guests no longer see where you are.", "good");
  });
  return card({ title: "Following", icon: "activity", id: "sh-follow" },
    h("p", { class: "small" }, paused ? "Paused: guests keep the shared views, not where you are."
      : "While a link is active, guests may follow the view you are on and see your latest actions."),
    h("div", { class: "btns" }, b));
}

function linkRow(l, redraw) {
  const tone = { active: "good", expired: "neutral", revoked: "neutral" }[l.state] || "neutral";
  const rev = l.state === "active" ? button("Revoke", { kind: "small", icon: "x", "data-control": "observe_revoke", key: "share:revoke:" + l.id,
    onclick: (e) => { if (needPerson()) act(e.currentTarget.parentNode, async () => { await api("POST", "/api/observe/revoke", Object.assign({ link: l.id }, signed())); followNow(); say(l.id + " revoked: it is refused from now on.", "good"); redraw(false); }); } }) : null;
  return h("li", { class: "sh-link", "data-id": l.id },
    h("div", { class: "sh-link-main" }, h("b", null, l.id + " "), datum(l.scope_title), l.guest ? [" · for ", datum(l.guest)] : null, " ",
      chip(tone, l.state === "active" ? "eye" : "clock", l.state), l.scope === "platform" ? chip("info", "globe", "Platform-wide") : chip("neutral", "folder", "Project")),
    h("p", { class: "small muted" }, "Expires " + localDateTime(l.expires) + " · " + (l.last_opened ? "last opened " + localDateTime(l.last_opened) + " (" + plural(l.opens || 0, "visit") + ")" : "not opened yet")
      + " · by ", datum(l.created_by)),
    l.watching && l.watching.length ? h("p", { class: "small sh-watch" }, icon("eye"), " Watching now: ", datum(l.watching.join(", "))) : null,
    rev ? h("div", { class: "btns" }, rev) : null);
}

function commentRow(c, titles) {
  return h("li", { class: "sh-comment", "data-id": c.id }, h("b", null, datum(c.guest)), " ", chip("accent", "user", "Guest"),
    h("span", { class: "small muted" }, " on ", datum(titles[c.project] || c.project), c.about ? " · " + c.about : "", " · " + localDateTime(c.at)),
    h("p", { "data-ud": "" }, c.text));
}

function suggestionRow(s, titles, redraw) {
  const decide = (verdict) => (e) => {
    if (!needPerson()) return;
    act(e.currentTarget.parentNode, async () => {
      await api("POST", "/api/projects/" + enc(s.project) + "/observe/suggestions", Object.assign({ suggestion: s.id, verdict }, signed()));
      say(verdict === "accept" ? s.question + " is answered, signed by you." : "Declined: " + s.question + " stays open.", "good");
      redraw(false);
    });
  };
  return h("li", { class: "sh-sugg", "data-id": s.id }, h("b", null, s.id + " · " + s.question + " "), chip("accent", "user", "from " + s.guest),
    h("span", { class: "small muted" }, " ", datum(titles[s.project] || s.project)),
    h("p", { "data-ud": "" }, s.text),
    s.state === "waiting" ? h("div", { class: "btns" },
      button("Confirm as my answer", { kind: "small primary human", icon: "check", "data-control": "observe_suggestion", key: "share:accept:" + s.id, onclick: decide("accept") }),
      button("Decline", { kind: "small", icon: "x", "data-control": "observe_suggestion", key: "share:decline:" + s.id, onclick: decide("decline") }))
      : h("p", { class: "small muted" }, s.state + (s.by ? " by " + s.by : "")));
}

export async function renderShare(seq) {
  if (seq !== undefined && seq !== S.seq) return;
  const main = document.getElementById("main");
  document.title = "Share · Rihmasto";
  const body = h("div", { class: "sh-body" }, h("p", { class: "muted", "aria-busy": "true" }, "Reading your observer links…"));
  fill(main, pageHead("Share", pick("Let a colleague watch your work, read only, for a while: they see what you see and can comment, never decide or change.",
    "Observer links: read-only, time-limited, hashed, revocable; guest comments and intake suggestions recorded in the ledger."), { icon: "eye" }), body);
  const redraw = async (first) => {
    let d;
    try { d = await api("GET", "/api/observe"); } catch (e) { fill(body, h("div", { class: "note critical" }, icon("alert"), h("span", null, "Your observer links could not be read: " + e.message))); return; }
    const titles = Object.fromEntries((d.projects || []).map((p) => [p.pid, p.title]));
    const kept = first ? null : body.querySelector("#sh-make-h");
    const make = kept ? kept.closest(".card") : makeForm(d, redraw);
    const links = d.links || [];
    const waiting = (d.suggestions || []).filter((s) => s.state === "waiting");
    fill(body, make, followCard(),
      card({ title: "Your links", icon: "link", id: "sh-links" }, links.length
        ? h("ul", { class: "sh-list", "data-control": "observe_watching" }, links.map((l) => linkRow(l, redraw)))
        : emptyState("share", null, { icon: "eye" })),
      card({ title: "Guests' suggestions", icon: "comment", id: "sh-sugg" }, (d.suggestions || []).length
        ? h("ul", { class: "sh-list" }, waiting.concat((d.suggestions || []).filter((s) => s.state !== "waiting").slice(0, 10)).map((s) => suggestionRow(s, titles, redraw)))
        : emptyState("share_suggestions", null, { icon: "comment" })),
      card({ title: "Guests' comments", icon: "message-square", id: "sh-comments" }, (d.comments || []).length
        ? h("ul", { class: "sh-list", "data-control": "observe_comments" }, d.comments.map((c) => commentRow(c, titles)))
        : emptyState("share_comments", null, { icon: "message-square" })));
  };
  await redraw(true);
}
