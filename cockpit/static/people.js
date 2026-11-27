/* People and access: solo or team (kernel/team.py, kernel/team_access.py, kernel/agent_personas.py; FR-PPL1).
   Solo, the default: one person, named once, acts in every persona; each decision is signed with the persona it
   needs and the record names it. Team: personas become people (the platform's own users, signed in with one-use
   links) and groups from an identity provider (Entra ID, AWS, Google or any OIDC), with project roles and the
   pages each persona sees. A persona may be given to an agent by delegation. Settings, People and access holds
   it all; the first visit asks "Just me" or "A team"; Ask Rihma proposes the same moves (PROPOSALS). */

import { tw } from "./words.js";
import {
  S, $, $$, h, fill, icon, chip, api, say, signed, needPerson, enc, button, card, personaLabel, store, nav,
  AuthError, PROPOSALS, FACTORY_PID, plural, heldPersonas, cap,
} from "./core.js";

const PRESETS = [["oidc", "Any OIDC provider"], ["oauth2-proxy", "Microsoft Entra ID or Okta through oauth2-proxy"],
  ["aws-alb", "AWS Application Load Balancer"], ["google-iap", "Google Cloud IAP"]];
const PAGE_LABEL = { review_all: "Review", home: "Home", square: "Square", catalogue: "Catalogue", projects: "Projects",
  inbox_all: "Inbox", insights_all: "Insights", floor: "Floor", jobs: "Jobs", automations_all: "Automations",
  health_all: "Health", agents_all: "Agent activity" };
const asIT = () => Object.assign(signed(), { persona: "it" });      // only IT changes who works here
const errorOf = (e) => (e instanceof AuthError ? null : e.message);

// -- the sign-in card of team mode --------------------------------------------------------------------------

export function teamSignInCard(message) {
  return h("div", { class: "signin" }, h("div", { class: "card signin-card" },
    h("span", { class: "card-ic big" }, icon("key")), h("h1", null, "Sign in"),
    message ? h("p", { class: "toast-inline warning" }, icon("alert"), message) : null,
    h("p", null, "This factory works in team mode. Open the one-use sign-in link you were sent: an invite, or a sign-in "
      + "link from the person who looks after people and access here. Each link works once."),
    h("p", { class: "muted small" }, "On the machine that runs Rihmasto: ", h("code", null, "rihmasto access link <user> --kind sign_in"),
      " prints a new one.")));
}

// -- the first visit: Just me, or a team --------------------------------------------------------------------

/* Two native radios (Just me is the default) and what each means. ``apply(name)`` records the choice once the
   person starts: solo names the one person; team turns team mode on with them as its first user, and this tab
   keeps a session as that user. Answers a line for the toast. */
export function whoWorksHere(onChange) {
  let mode = "solo";
  const next = h("p", { class: "small muted", id: "fr-mode-d" });
  const words = { solo: "You act in every persona: no set-up, no switching. Each decision says which persona it used.",
    team: "Personas become people and groups. You become the first user; then add people or connect your identity "
      + "provider (Entra ID, AWS, Google or any OIDC) in Settings, People and access." };
  const radio = (value, label) => {
    const id = "fr-mode-" + value;
    const r = h("input", { type: "radio", name: "fr-mode", id, value, checked: value === mode || null, "data-control": "people_mode",
      "aria-describedby": "fr-mode-d" });
    r.addEventListener("change", () => { mode = value; next.textContent = words[mode]; if (onChange) onChange(mode); });
    return h("label", { class: "chk-l fr-mode-opt", for: id }, r, " " + label);
  };
  next.textContent = words.solo;
  const el = h("fieldset", { class: "fr-mode" }, h("legend", null, "Who works here"),
    h("div", { class: "fr-mode-row" }, radio("solo", "Just me"), radio("team", "A team or an organisation")), next);
  return { el, value: () => mode, apply: (name) => applyMode(mode, name) };
}

async function applyMode(mode, name) {
  if (mode === "solo") {
    await api("POST", "/api/people/solo", { person: name, persona: S.persona });
    return "Just you: you act in every " + tw("persona") + ".";
  }
  const out = await api("POST", "/api/people/mode", Object.assign({ mode: "team", reason: "the first-run choice" }, asIT()));
  keepSession(out);
  return "Team mode is on: add people or connect your identity provider in Settings, People and access.";
}

function keepSession(out) {
  if (!out || !out.session) return;
  S.token = out.session;
  store.set("gf.token", S.token);
  S.teamSignIn = out.mode === "team";
}

// -- the Inbox through every persona: a filter by the persona each card is decided as ------------------------

export function inboxPersonaFilter(cards) {
  const counts = {};
  cards.forEach((c) => { counts[c.decide_as] = (counts[c.decide_as] || 0) + 1; });
  const pick = h("select", { id: "ib-as", "data-key": "ib-as", "data-control": "viewing_as" },
    h("option", { value: "" }, "Every persona (" + cards.length + ")"),
    Object.keys(counts).map((p) => h("option", { value: p, selected: S.inboxAs === p || null }, personaLabel(p) + " (" + counts[p] + ")")));
  pick.addEventListener("change", () => { S.inboxAs = pick.value || null; nav.rerender(); });
  return h("div", { class: "filters ib-as-f" }, h("label", { for: "ib-as" }, "Cards you decide as"), pick);
}

// -- Settings, People and access ----------------------------------------------------------------------------

export function peopleCard(projects) {
  const body = h("div", { class: "ppl-box" }, h("p", { class: "muted" }, "Reading who works here…"));
  const draw = async () => {
    try { fill(body, drawPeople(await api("GET", "/api/people"), projects || [], draw)); }
    catch (e) { if (!(e instanceof AuthError)) fill(body, h("p", { class: "note warning" }, icon("alert"), e.message)); }
  };
  draw();
  return card({ title: "People and access", icon: "users", id: "set-people", cls: "ppl-card", dataId: "people_access",
    info: "Solo: one person acts in every persona. Team: personas become people and groups, each deciding only as the "
      + "personas they hold, on the projects they may see. Every change is signed and recorded in the factory's ledger.",
    tools: [h("span", { "data-control": "people_access" }, chip("info", "shield", "Who decides"))] }, body);
}

function status() { return h("p", { class: "mod-status", role: "status", "aria-live": "polite" }); }

async function run(st, fn, done, redraw) {
  if (!needPerson()) return;
  try {
    const out = await fn();
    fill(st, icon("check"), " " + done(out));
    say(done(out), "good");
    if (redraw) await redraw();
  } catch (e) { const m = errorOf(e); if (m) { fill(st, icon("alert"), " " + m); say(m, "critical"); } }
}

function drawPeople(d, projects, redraw) {
  const st = status();
  const head = h("p", { class: "ppl-now", "data-key": "people:now" }, h("b", null, d.mode === "team" ? "Team mode. " : d.mode === "it" ? "IT's access file. " : "Solo mode. "), h("span", { "data-ud": "" }, d.words));   // the kernel's sentence
  if (d.mode === "it") return [head, agentsBlock(d, projects, redraw)];
  if (d.mode === "team" && !heldPersonas().includes("it")) {      // a member who is not IT reads, IT changes
    return [head, h("p", { class: "note" }, icon("shield"), h("span", null, "IT changes who works here. You decide as "
      + (heldPersonas().map(personaLabel).join(", ") || "no persona") + ".")), agentsBlock(d, projects, redraw)];
  }
  const toggle = button(d.mode === "team" ? "Back to just me" : "Turn on team mode", { icon: d.mode === "team" ? "user" : "users",
    kind: "small" + (d.mode === "team" ? "" : " primary"), key: "people:mode", "data-control": "people_mode",
    onclick: () => run(st, async () => {
      const out = await api("POST", "/api/people/mode", Object.assign({ mode: d.mode === "team" ? "solo" : "team", reason: "Settings" }, asIT()));
      keepSession(out);
      if (out.mode === "team" && out.user) { S.person = out.user.name; }
      const meta = await api("GET", "/api/meta");
      S.meta = meta;
      if (nav.accessChanged) nav.accessChanged();     // the top bar says team mode at once, without a reload
      else if (nav.drawAccess) nav.drawAccess();      // the header says the new mode at once (FR-NVL3)
      return out;
    }, (out) => (out.mode === "team" ? "Team mode is on, and every record stays. You are its first user." : "Back to solo: you act in every persona again."), redraw) });
  const out = [head, h("div", { class: "btns" }, toggle), st];
  if (d.mode !== "team") out.push(soloName(d, redraw));
  else out.push(usersBlock(d, projects, redraw), groupsBlock(d, projects, redraw), rolesBlock(d, projects, redraw),
    viewsBlock(d, redraw), idpBlock(d, redraw));
  out.push(agentsBlock(d, projects, redraw));
  return out;
}

function soloName(d, redraw) {
  const st = status();
  const name = h("input", { id: "ppl-solo-name", maxlength: "200", value: (d.solo && d.solo.name) || S.person, autocomplete: "name" });
  const save = button("Save my name", { icon: "check", kind: "small", key: "people:solo", "data-control": "people_name",
    onclick: () => run(st, async () => {
      S.person = name.value.trim();
      store.set("gf.person", S.person);
      return api("POST", "/api/people/solo", { person: S.person, persona: S.persona });
    }, (o) => "Your name is " + o.name + ": it signs every decision, in every persona.", redraw) });
  return h("div", { class: "ppl-sec" }, h("div", { class: "field" }, h("label", { for: "ppl-solo-name" }, "Your name"), name), save, st);
}

function personaBoxes(prefix, chosen) {
  return h("div", { class: "ppl-personas", role: "group", "aria-label": "Personas" }, S.personas.map((p) => {
    const id = prefix + "-" + p.id;
    return h("label", { class: "chk-l", for: id }, h("input", { type: "checkbox", id, value: p.id, checked: (chosen || []).includes(p.id) || null }), " " + p.label);
  }));
}
const boxed = (box) => $$("input:checked", box).map((x) => x.value);

function scopeSelect(id, projects, label) {
  return h("div", { class: "field" }, h("label", { for: id }, label || "Where"),
    h("select", { id }, h("option", { value: "*" }, "Every project"),
      projects.filter((p) => p.id !== FACTORY_PID).map((p) => h("option", { value: p.id }, p.title))));
}
const scopeOf = (id) => { const v = $("#" + id).value; return v === "*" ? "*" : [v]; };

function usersBlock(d, projects, redraw) {
  const st = status();
  const linkBox = h("div", { class: "ppl-link", hidden: true });
  const rows = d.users.map((u) => h("li", { class: "ppl-row", "data-key": "user:" + u.id },
    h("div", { class: "sig-b" }, h("b", null, u.name + " "), h("span", { class: "mono muted small" }, u.id),
      h("div", { class: "sig-m" }, h("span", null, u.personas.map(personaLabel).join(", ") || "no persona"),
        h("span", null, u.scope === "*" ? "every project" : plural(u.scope.length, "project")))),
    u.active ? chip("good", "check-circle", "Active") : chip("neutral", "x-circle", "Deactivated"),
    u.active ? button("Invite link", { icon: "link", kind: "small", key: "user:" + u.id + ":link", "data-control": "people_invite", aria: "Invite link for " + u.name,
      onclick: () => run(st, async () => {
        const out = await api("POST", "/api/people/users/" + enc(u.id) + "/link", Object.assign({ kind: "invite" }, asIT()));
        fill(linkBox, h("label", { for: "ppl-link-url" }, "One-use link for " + u.name + ", shown once"),
          h("input", { id: "ppl-link-url", readonly: true, value: out.link.url }));
        linkBox.hidden = false;
        return out;
      }, (o) => "A one-use link for " + o.link.name + " until " + o.link.expires + ".") }) : null,
    u.owner ? null : button(u.active ? "Deactivate" : "Activate", { icon: u.active ? "x" : "check", kind: "small quiet", key: "user:" + u.id + ":active",
      "data-control": "people_deactivate", aria: (u.active ? "Deactivate " : "Activate ") + u.name,
      onclick: () => run(st, () => api("PUT", "/api/people/users/" + enc(u.id), Object.assign({ active: !u.active }, asIT())),
        (o) => o.user.name + (o.user.active ? " is active again." : " is deactivated: their sessions and links stop now."), redraw) })));
  const name = h("input", { id: "ppl-new-name", maxlength: "200", autocomplete: "off" });
  const boxes = personaBoxes("ppl-new", ["stakeholder"]);
  const add = button("Add the user", { icon: "plus", kind: "small primary", key: "people:add", "data-control": "people_add_user",
    onclick: () => run(st, () => api("POST", "/api/people/users", Object.assign({ name: name.value.trim(), personas: boxed(boxes),
      scope: scopeOf("ppl-new-scope") }, asIT())), (o) => o.user.name + " is a user. Send them an invite link.", redraw) });
  return h("section", { class: "ppl-sec", "aria-labelledby": "ppl-users-h" }, h("h4", { id: "ppl-users-h" }, "People"),
    h("ul", { class: "emb-list" }, rows), linkBox,
    h("div", { class: "ppl-form" }, h("div", { class: "field" }, h("label", { for: "ppl-new-name" }, "Name"), name), boxes,
      scopeSelect("ppl-new-scope", projects), add), st);
}

function groupsBlock(d, projects, redraw) {
  const st = status();
  const group = h("input", { id: "ppl-group", maxlength: "256", placeholder: "the group's id, as the token lists it" });
  const to = h("select", { id: "ppl-group-to" }, S.personas.map((p) => h("option", { value: p.id }, p.label)));
  const save = button("Map the group", { icon: "users", kind: "small", key: "people:group", "data-control": "people_map_group",
    onclick: () => run(st, () => api("POST", "/api/people/groups", Object.assign({ group: group.value.trim(), to: to.value,
      scope: scopeOf("ppl-group-scope") }, asIT())), (o) => "Group " + o.group.group + " decides as " + personaLabel(o.group.persona) + ".", redraw) });
  return h("section", { class: "ppl-sec", "aria-labelledby": "ppl-groups-h" }, h("h4", { id: "ppl-groups-h" }, "Groups from your identity provider"),
    d.groups.length ? h("ul", { class: "ppl-list" }, d.groups.map((g) => h("li", null, h("span", { class: "mono" }, g.group), " → " + personaLabel(g.persona)
      + (g.scope === "*" ? ", every project" : ", " + g.scope.join(", "))))) : h("p", { class: "muted small" }, "No group is mapped yet."),
    h("div", { class: "ppl-form" }, h("div", { class: "field" }, h("label", { for: "ppl-group" }, "Group"), group),
      h("div", { class: "field" }, h("label", { for: "ppl-group-to" }, "Decides as"), to), scopeSelect("ppl-group-scope", projects), save), st);
}

function rolesBlock(d, projects, redraw) {
  const st = status();
  const own = projects.filter((p) => p.id !== FACTORY_PID);
  if (!own.length) return null;
  const pid = h("select", { id: "ppl-role-project" }, own.map((p) => h("option", { value: p.id }, p.title)));
  const who = h("select", { id: "ppl-role-user" }, d.users.filter((u) => u.active).map((u) => h("option", { value: u.id }, u.name)));
  const boxes = personaBoxes("ppl-role", []);
  const save = button("Set the project's roles", { icon: "check", kind: "small", key: "people:role", "data-control": "people_role",
    onclick: () => run(st, () => api("POST", "/api/people/roles", Object.assign({ project: pid.value, user: who.value, personas: boxed(boxes) }, asIT())),
      (o) => "On that project they hold " + (o.role.personas.map(personaLabel).join(", ") || "no persona") + ".", redraw) });
  return h("section", { class: "ppl-sec", "aria-labelledby": "ppl-roles-h" }, h("h4", { id: "ppl-roles-h" }, "A project's own roles"),
    h("p", { class: "muted small" }, "On one project, a person holds exactly these personas, whatever they hold elsewhere."),
    h("div", { class: "ppl-form" }, h("div", { class: "field" }, h("label", { for: "ppl-role-project" }, "Project"), pid),
      h("div", { class: "field" }, h("label", { for: "ppl-role-user" }, "Person"), who), boxes, save), st);
}

function viewsBlock(d, redraw) {
  const st = status();
  const to = h("select", { id: "ppl-views-to" }, S.personas.map((p) => h("option", { value: p.id }, p.label)));
  const box = h("div", { class: "ppl-personas", role: "group", "aria-label": "Pages kept from this persona" });
  const drawBoxes = () => fill(box, (d.pages || []).map((pg) => h("label", { class: "chk-l", for: "ppl-v-" + pg },
    h("input", { type: "checkbox", id: "ppl-v-" + pg, value: pg, checked: ((d.views || {})[to.value] || []).includes(pg) || null }), " " + (PAGE_LABEL[pg] || pg))));
  to.addEventListener("change", drawBoxes);
  drawBoxes();
  const save = button("Keep these pages from the persona", { icon: "eye", kind: "small", key: "people:views", "data-control": "people_views",
    onclick: () => run(st, () => api("PUT", "/api/people/views", Object.assign({ to: to.value, hidden: boxed(box) }, asIT())),
      (o) => personaLabel(o.views.persona) + " does not see " + (o.views.hidden.map((p) => PAGE_LABEL[p] || p).join(", ") || "nothing hidden") + ".", redraw) });
  return h("section", { class: "ppl-sec", "aria-labelledby": "ppl-views-h" }, h("h4", { id: "ppl-views-h" }, "Pages per persona"),
    h("div", { class: "field" }, h("label", { for: "ppl-views-to" }, cap(tw("persona"))), to), box, save, st);
}

function idpBlock(d, redraw) {
  const st = status();
  const idp = d.idp || {};
  const field = (key, label, hint) => h("div", { class: "field" }, h("label", { for: "ppl-idp-" + key }, label),
    h("input", { id: "ppl-idp-" + key, value: idp[key] || "", placeholder: hint || "" }));
  const preset = h("select", { id: "ppl-idp-preset" }, PRESETS.map(([v, l]) => h("option", { value: v, selected: idp.preset === v || null }, l)));
  const save = button("Save the provider", { icon: "key", kind: "small", key: "people:idp", "data-control": "people_idp",
    onclick: () => run(st, () => {
      const v = (k) => $("#ppl-idp-" + k).value.trim();
      const settings = { preset: preset.value, issuer: v("issuer"), origin: v("origin"), audience: v("audience"), groups_claim: v("groups_claim"),
        token_header: v("token_header"), subject_claim: v("subject_claim") };
      return api("PUT", "/api/people/idp", Object.assign({ idp: settings, jwks_url: v("jwks_url") }, asIT()));
    }, () => "The identity provider is saved. Fetch or paste its public keys next.", redraw) });
  const fetchKeys = button("Fetch the keys", { icon: "download", kind: "small", key: "people:fetch", "data-control": "people_keys",
    onclick: () => run(st, () => api("POST", "/api/people/keys", Object.assign({ fetch: true }, asIT())),
      (o) => plural(o.keys.length, "public key") + " kept: " + o.keys.join(", ") + ".", redraw) });
  const token = h("textarea", { id: "ppl-token", rows: "2", placeholder: "a token from the provider's own test tools" });
  const result = h("div", { class: "ppl-test", role: "status", "aria-live": "polite" });
  const test = button("Test with a token", { icon: "check-circle", kind: "small", key: "people:test", "data-control": "people_test_token",
    onclick: async () => {
      try {
        const out = await api("POST", "/api/people/test-token", { token: token.value.trim() });
        fill(result, out.ok ? h("p", { class: "note" }, icon("check"), h("span", null, out.name + " (" + out.identity + "), groups "
          + (out.groups.join(", ") || "none") + ", signs in as " + (out.grants.map((g) => personaLabel(g.persona)).join(", ") || "nothing")))
          : h("p", { class: "note warning" }, icon("alert"), h("span", null, out.refused)));
      } catch (e) { const m = errorOf(e); if (m) fill(result, h("p", { class: "note warning" }, icon("alert"), m)); }
    } });
  return h("section", { class: "ppl-sec", "aria-labelledby": "ppl-idp-h" }, h("h4", { id: "ppl-idp-h" }, "Identity provider (optional)"),
    h("p", { class: "muted small" }, "Entra ID, AWS, Google or any OIDC provider, through the sign-in proxy in front of the cockpit. "
      + "Map its groups above; a token is verified with the provider's public keys, kept here: " + ((d.keys || []).join(", ") || "none yet") + "."),
    h("div", { class: "field" }, h("label", { for: "ppl-idp-preset" }, "Kind"), preset),
    field("issuer", "Issuer", "https://login.example.org"), field("origin", "Address people open", "https://rihmasto.example.org"),
    field("audience", "Audience (client id)"), field("groups_claim", "Groups claim", "groups"),
    field("token_header", "Token header (any OIDC)", "Authorization"), field("subject_claim", "Subject claim", "sub, or oid for Entra ID"),
    field("jwks_url", "JWKS address", "https://login.example.org/keys"),
    h("div", { class: "btns" }, save, fetchKeys), h("div", { class: "field" }, h("label", { for: "ppl-token" }, "A token to test"), token),
    test, result, st);
}

function agentsBlock(d, projects, redraw) {
  const st = status();
  const own = projects.filter((p) => p.id !== FACTORY_PID);
  const list = (d.agents || []).length ? h("ul", { class: "ppl-list", "data-control": "people_agents" }, d.agents.map((a) =>
    h("li", { "data-key": "agent:" + a.project + ":" + a.id }, h("b", null, a.project_title + ": "), a.words)))
    : h("p", { class: "muted small", "data-control": "people_agents" }, "No " + tw("persona") + " is given to an agent.");
  if (!own.length) return h("section", { class: "ppl-sec" }, h("h4", null, "Agents acting as a " + tw("persona")), list);
  const pid = h("select", { id: "ppl-ag-project" }, own.map((p) => h("option", { value: p.id }, p.title)));
  const persona = h("select", { id: "ppl-ag-persona" }, S.personas.filter((p) => p.decides.length).map((p) => h("option", { value: p.id }, p.label)));
  const agent = h("input", { id: "ppl-ag-name", maxlength: "40", value: "ops-agent" });
  const kinds = h("div", { class: "ppl-personas", role: "group", "aria-label": "Kinds of card it may decide" });
  const never = Object.keys((S.meta.autopilot || {}).never || {});
  const drawKinds = () => {
    const p = S.personas.find((x) => x.id === persona.value) || { decides: [] };
    fill(kinds, p.decides.filter((k) => !never.includes(k)).map((k) => h("label", { class: "chk-l", for: "ppl-ag-k-" + k },
      h("input", { type: "checkbox", id: "ppl-ag-k-" + k, value: k, checked: true }), " " + k.replace("_", " "))));
  };
  persona.value = "operations";
  persona.addEventListener("change", drawKinds);
  drawKinds();
  const until = h("select", { id: "ppl-ag-until" }, [["1d", "a day"], ["3d", "three days"], ["7d", "a week"]].map(([v, l]) => h("option", { value: v }, l)));
  const give = button("Give the " + tw("persona") + " to the agent", { icon: "bot", kind: "small", key: "people:agent", "data-control": "people_delegate_agent",
    onclick: () => run(st, () => api("POST", "/api/projects/" + enc(pid.value) + "/agent-personas", Object.assign(signed(), {
      persona: persona.value, agent: agent.value.trim(), agent_kind: "bridge", kinds: boxed(kinds), until: until.value })),
    (o) => o.delegation.words + ".", redraw) });
  return h("section", { class: "ppl-sec", "aria-labelledby": "ppl-ag-h" }, h("h4", { id: "ppl-ag-h" }, "Agents acting as a " + tw("persona")),
    h("p", { class: "muted small" }, "An agent decides only the kinds of card you give it, on one project, until the date you set. "
      + "Revoke it on the project's Track view."), list,
    h("div", { class: "ppl-form" }, h("div", { class: "field" }, h("label", { for: "ppl-ag-project" }, "Project"), pid),
      h("div", { class: "field" }, h("label", { for: "ppl-ag-persona" }, cap(tw("persona"))), persona),
      h("div", { class: "field" }, h("label", { for: "ppl-ag-name" }, "Agent"), agent), kinds,
      h("div", { class: "field" }, h("label", { for: "ppl-ag-until" }, "Until"), until), give), st);
}

// -- Ask Rihma's proposals for people and access ---------------------------------------------------------------

Object.assign(PROPOSALS, {
  people_mode: { words: ["Change who works here", "users"],
    describe: (a) => [a.mode === "team" ? "Turn on team mode: you become its first user; every record stays" : "Back to just you, in every persona"],
    call: async (a) => { const out = await api("POST", "/api/people/mode", Object.assign({ mode: a.mode, reason: "asked Rihma" }, asIT())); keepSession(out); return out; } },
  people_add_user: { words: ["Add a user", "user"],
    describe: (a) => [a.name + " as " + (a.personas || []).map(personaLabel).join(", ")],
    call: (a) => api("POST", "/api/people/users", Object.assign({ name: a.name, personas: a.personas || [], scope: "*" }, asIT())) },
  people_map_group: { words: ["Map a group to a persona", "users"],
    describe: (a) => ["Group " + a.group + " decides as " + personaLabel(a.to)],
    call: (a) => api("POST", "/api/people/groups", Object.assign({ group: a.group, to: a.to, scope: "*" }, asIT())) },
  people_delegate_agent: { words: ["Give a persona to an agent", "bot"],
    describe: (a) => [personaLabel(a.persona) + " to " + a.agent + " for " + (a.kinds || []).join(", ") + " cards, until " + a.until],
    call: (a, pid) => api("POST", "/api/projects/" + enc(pid) + "/agent-personas", Object.assign(signed(), {
      persona: a.persona, agent: a.agent, agent_kind: a.agent_kind || "bridge", kinds: a.kinds, until: a.until || "7d" })) },
});
