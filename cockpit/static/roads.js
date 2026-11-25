/* Paved roads (kernel/road_settings.py, FR-GCP1): Settings shows every road, ready or exactly what is
   missing, and IT configures a Google Cloud road there (a Cloud Run service, or a Cloud Run job Cloud
   Scheduler runs); a project's Releases view shows where each environment of its plan deploys, a scheduled
   job's last executions, and lets IT choose the road, the workload and the schedule. Settings also lists the
   kinds of systems a capability can reach, the Google Drive connector among them (FR-GDR1). Every write is
   signed with the person and persona; secrets are named, never given. */

import { S, h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, openModal, closeModal, segmented, empty } from "./core.js";

const KIND = { "local-process": "Local process", docker: "Docker", "azure-containerapps": "Azure Container Apps", "gcp-cloudrun": "Google Cloud Run" };

function readyChip(r) {
  return r.ready ? chip("good", "check-circle", "Ready")
    : chip("warning", "alert", r.missing.length === 1 ? "1 thing missing" : r.missing.length + " things missing");
}

function missingList(items, id) {
  if (!items || !items.length) return null;
  return h("ul", { class: "road-missing small", id: id || null }, items.map((m) => h("li", null, m)));
}

function cloudrunLine(c) {
  if (!c) return null;
  const s = c.schedule;
  const where = c.project_id || Object.values(c.projects || {}).join(", ");
  return h("div", { class: "sig-m" }, h("span", { class: "mono" }, where || "no project"), h("span", null, c.region || "no region"),
    h("span", null, c.workload === "job" ? "a scheduled job" : "a service"),
    s ? h("span", { class: "mono" }, s.cron + " " + (s.time_zone || "")) : null,
    c.runtime_service_account ? h("span", { class: "mono" }, "runs as " + c.runtime_service_account) : null);
}

function roadRow(r) {
  return h("li", { class: "road-row", "data-key": "road:" + r.name },
    h("span", { class: "cat-ic" }, icon(r.kind === "gcp-cloudrun" ? "globe" : r.kind === "docker" ? "package" : "server")),
    h("div", { class: "sig-b" }, h("b", null, r.name + " "), h("span", { class: "muted small" }, KIND[r.kind] || r.kind || "unknown kind"),
      h("div", { class: "sig-m" }, h("span", null, (r.environments || []).join(", ")), r.owner ? h("span", null, r.owner) : null,
        r.builtin ? h("span", null, "built in") : null, r.secrets.length ? h("span", null, "secrets by name: " + r.secrets.join(", ")) : null),
      cloudrunLine(r.cloudrun), missingList(r.missing)),
    readyChip(r));
}

// -- Settings: the roads, and a form for a Google Cloud road ----------------------------------------------

function field(id, label, value, opts) {
  const o = opts || {};
  const input = h(o.area ? "textarea" : "input", { id, maxlength: o.max || "300", autocomplete: "off", spellcheck: "false",
    placeholder: o.placeholder || "", rows: o.area ? "3" : null });
  input.value = value || "";
  return { el: h("div", { class: "field" }, h("label", { for: id }, label), input, o.hint ? h("small", { class: "muted" }, o.hint) : null), input };
}

function secretsOf(text) {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const i = l.indexOf("=");
    return { name: l.slice(0, i).trim(), ref: l.slice(i + 1).trim() };
  });
}

function gcpForm(onSaved) {
  const f = {
    name: field("gcp-name", "The road's name", "gcp-cloudrun"),
    test: field("gcp-test", "Google Cloud project for the test environment (staging)", "", { placeholder: "example-test-123" }),
    prod: field("gcp-prod", "Google Cloud project for production", "", { placeholder: "example-prod-123" }),
    region: field("gcp-region", "Region", "europe-north1"),
    repo: field("gcp-repo", "Artifact Registry repository", "", { placeholder: "europe-north1-docker.pkg.dev/example-build-123/rihmasto" }),
    who: field("gcp-who", "The service account Rihmasto deploys as (impersonated), or a workload identity file", "",
      { placeholder: "deployer@example-prod-123.iam.gserviceaccount.com" }),
    runtime: field("gcp-runtime", "The service account the product runs as (share the Drive folder with it)", "",
      { placeholder: "runtime@example-prod-123.iam.gserviceaccount.com" }),
    cron: field("gcp-cron", "Schedule (cron: minute hour day month weekday)", "0 6 * * *"),
    tz: field("gcp-tz", "Time zone", "Europe/Helsinki"),
    retries: field("gcp-retries", "Retries when a run fails (0 to 5)", "1"),
    sched: field("gcp-sched", "The service account Cloud Scheduler runs the job as", "", { placeholder: "scheduler@example-prod-123.iam.gserviceaccount.com" }),
    egress: field("gcp-egress", "Egress rule IT keeps (shown at the deploy gate)", "Google APIs only, through IT's VPC"),
    connector: field("gcp-connector", "VPC connector (optional; egress then goes through it)", "", { placeholder: "rihmasto-connector" }),
    secrets: field("gcp-secrets", "Secrets from Secret Manager, by name: one NAME=sm:secret:version per line", "",
      { area: true, max: "2000", placeholder: "MODEL_API_KEY=sm:model-api-key:latest", hint: "Never a value: the name of the secret in Secret Manager." }),
  };
  let how = "service_account";
  let workload = "job";
  const job = h("div", { class: "np-part" }, h("div", { class: "row2" }, f.cron.el, f.tz.el), h("div", { class: "row2" }, f.retries.el, f.sched.el));
  const show = () => { job.hidden = workload !== "job"; };
  const whoSeg = segmented("gcp-how", [["service_account", "A service account"], ["credential_file", "A workload identity file"], ["ambient", "This host's own login"]],
    how, (v) => { how = v; f.who.input.disabled = v === "ambient"; }, { label: "How Rihmasto deploys" });
  const wlSeg = segmented("gcp-workload", [["job", "A scheduled job"], ["service", "A service (HTTP)"]], workload, (v) => { workload = v; show(); },
    { label: "What runs" });
  const mats = ["pilot", "production"].map((m) => h("label", { class: "chk", for: "gcp-m-" + m }, h("input", { type: "checkbox", id: "gcp-m-" + m, checked: true }), " " + m));
  show();
  const form = h("form", { class: "np-form", novalidate: true },
    h("p", { class: "note" }, icon("shield"), h("span", null, "Written to paved_roads.json, checked whole first; the factory's ledger records who configured it. "
      + "Deploys run only while gcloud is signed in on this host; until then the road says what is missing.")),
    f.name.el, h("div", { class: "row2" }, f.test.el, f.prod.el), h("div", { class: "row2" }, f.region.el, f.repo.el),
    h("div", { class: "field" }, h("label", null, "How Rihmasto deploys"), whoSeg), f.who.el, f.runtime.el,
    h("div", { class: "field" }, h("label", null, "What runs"), wlSeg), job,
    h("div", { class: "row2" }, f.egress.el, f.connector.el), f.secrets.el,
    h("div", { class: "field" }, h("label", null, "Maturities this road serves"), h("div", { class: "btns" }, mats)),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "configure_gcp_road", "data-key": "gcp-save" }, icon("check"), "Save the road")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    const v = (k) => f[k].input.value.trim();
    const road = { kind: "gcp-cloudrun", configured: true, environments: ["staging", "production"],
      projects: { staging: v("test"), production: v("prod") }, region: v("region"), repository: v("repo"),
      deployer: how === "ambient" ? { ambient: true } : { [how]: v("who") }, runtime_service_account: v("runtime"), workload,
      network: Object.assign({ ingress: "internal" }, v("connector") ? { egress: "private-ranges-only", vpc_connector: v("connector") } : {}),
      rules: { region: v("region"), egress: v("egress") }, secrets: secretsOf(f.secrets.input.value) };
    if (workload === "job") road.schedule = { cron: v("cron"), time_zone: v("tz"), retries: Number(v("retries") || 0), service_account: v("sched") };
    const maturity = ["pilot", "production"].filter((m) => document.getElementById("gcp-m-" + m).checked);
    act(form, async () => {
      const out = await api("PUT", "/api/roads/" + enc(v("name")), Object.assign({ road, maturity }, signed()));
      closeModal();
      say("The road " + out.road.name + " is configured" + (out.road.ready ? " and ready." : ". Still missing: " + out.road.missing.join("; ")), out.road.ready ? "good" : "warning");
      await onSaved();
    });
  });
  return form;
}

export function roadsCard() {
  const box = h("div", { class: "roads-box", "data-key": "set:roads" });
  loadRoads(box);
  return box;
}

async function loadRoads(box) {
  let v;
  try { v = await api("GET", "/api/roads"); } catch (e) {
    fill(box, card({ title: "Paved roads", icon: "server" }, h("p", { class: "muted" }, "The roads could not be read: " + e.message)));
    return;
  }
  const may = (v.deciders || []).includes(S.persona);
  const tool = may ? button("Configure a Google Cloud road", { icon: "plus", kind: "small primary", "data-control": "configure_gcp_road", key: "road-gcp-new",
    onclick: () => openModal("A Google Cloud road", gcpForm(() => loadRoads(box)), { icon: "globe", wide: true }) })
    : h("span", { class: "muted small" }, icon("user"), " IT configures the roads.");
  fill(box, card({ title: "Paved roads", icon: "server", id: "set-roads", cls: "roads-card", tools: [tool],
    info: "A product deploys only to a road IT configured: a test environment first, then production through IT's deploy gate. A road that is not ready says exactly what is missing." },
  h("p", { class: "note" }, icon("info"), h("span", null, "Kept in " + v.source + (v.exists ? "" : " (not written yet)") + ". Other kinds are edited in that file; see docs/guides/deploying.md.")),
  v.problems.length ? h("p", { class: "note warning" }, icon("alert"), h("span", null, v.problems.join("; "))) : null,
  h("ul", { class: "road-list", "data-control": "paved_roads" }, v.roads.map(roadRow))));
}

// -- Settings: the kinds of systems a capability can reach -----------------------------------------------

export function integrationsCard() {
  const box = h("div", { class: "kinds-box", "data-key": "set:kinds" });
  api("GET", "/api/integration-kinds").then((v) => {
    const g = v.gdrive;
    fill(box, card({ title: "Integrations a capability can reach", icon: "plug", id: "set-kinds",
      info: "A capability declares each system it reads or writes in its plan; IT binds it to the real system on the paved road and approves it. Credentials are named, never held." },
    h("div", { class: "drive-card", "data-control": "drive_connector", "data-key": "kind:gdrive" },
      h("b", null, "Google Drive "), h("span", { class: "muted small" }, "list new files in a folder, download one, upload a result"),
      h("dl", { class: "kv" },
        h("div", null, h("dt", null, "The product imports"), h("dd", { class: "mono" }, g.client)),
        h("div", null, h("dt", null, "Scopes"), h("dd", null, "read: " + g.scopes.read.map((s) => s.split("/").pop()).join(", ")
          + "; read-write: " + g.scopes["read-write"].map((s) => s.split("/").pop()).join(", "))),
        h("div", { class: "wide" }, h("dt", null, "Credentials, by name"), h("dd", null, g.credentials.join("; ")))),
      h("p", { class: "muted small" }, "On Google Cloud, share the folder with the road's runtime service account; no key is needed. Guide: " + g.guide + ".")),
    h("ul", { class: "kinds-list" }, v.kinds.map((k) => h("li", { "data-key": "kind:" + k.kind },
      h("b", null, k.kind), " ", h("span", { class: "muted small" }, k.family + " · via " + k.via.join(", ") + " · "
        + (k.client ? "the product imports " + k.client : k.connector)))))));
  }).catch((e) => fill(box, card({ title: "Integrations a capability can reach", icon: "plug" }, h("p", { class: "muted" }, "Not read: " + e.message))));
  return box;
}

// -- a project's Releases view: where it deploys ------------------------------------------------------------

function chooseForm(pid, v, onSaved) {
  const roads = v.roads.length ? v.roads : [];
  const pick = h("select", { id: "rd-road", "aria-label": "The paved road" }, roads.map((r) => h("option", { value: r.name, selected: r.name === v.chosen || null }, r.name + " (" + (KIND[r.kind] || r.kind) + ")")));
  const own = v.cloudrun || {};
  let workload = own.workload || "job";
  const cron = field("rd-cron", "Schedule (cron)", (own.schedule || {}).cron || "0 6 * * *");
  const tz = field("rd-tz", "Time zone", (own.schedule || {}).time_zone || "Europe/Helsinki");
  const retries = field("rd-retries", "Retries (0 to 5)", String((own.schedule || {}).retries ?? 1));
  const sched = field("rd-sched", "Cloud Scheduler's service account", (own.schedule || {}).service_account || "");
  const part = h("div", { class: "np-part" }, h("div", { class: "row2" }, cron.el, tz.el), h("div", { class: "row2" }, retries.el, sched.el));
  const seg = segmented("rd-workload", [["job", "A scheduled job"], ["service", "A service (HTTP)"]], workload, (x) => { workload = x; part.hidden = x !== "job"; }, { label: "What runs" });
  const gcpPart = h("div", null, h("div", { class: "field" }, h("label", null, "What runs"), seg), part);
  const kindOf = () => (roads.find((r) => r.name === pick.value) || {}).kind;
  const show = () => { gcpPart.hidden = kindOf() !== "gcp-cloudrun"; part.hidden = workload !== "job"; };
  pick.addEventListener("change", show);
  show();
  const form = h("form", { class: "np-form", novalidate: true },
    h("div", { class: "field" }, h("label", { for: "rd-road" }, "The paved road"), pick), gcpPart,
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "choose_road", "data-key": "rd-save" }, icon("check"), "Choose")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    const body = Object.assign({ road: pick.value }, signed());
    if (kindOf() === "gcp-cloudrun") {
      body.workload = workload;
      if (workload === "job") body.schedule = { cron: cron.input.value.trim(), time_zone: tz.input.value.trim(), retries: Number(retries.input.value || 0), service_account: sched.input.value.trim() };
    }
    act(form, async () => {
      await api("PUT", "/api/projects/" + enc(pid) + "/road", body);
      closeModal();
      say("This project now deploys on " + body.road + ".", "good");
      await onSaved();
    });
  });
  return form;
}

function jobStatus(js) {
  if (!js) return null;
  const tone = js.verdict === "passed" ? ["good", "check-circle"] : js.verdict === "failed" ? ["critical", "x-circle"] : ["nm", "dashed"];
  return h("div", { class: "rel-ho" }, h("div", { class: "rs-h" }, icon("clock"), h("b", null, "The job's last executions "), chip(tone[0], tone[1], js.verdict),
    h("span", { class: "muted small" }, (js.health && js.health.reason) || "", js.at ? " · read " + js.at : "")),
  (js.executions || []).length ? h("ul", { class: "road-missing small" }, js.executions.map((x) => h("li", null, (x.name || "?") + ": " + x.state + (x.started ? " at " + x.started : "")))) : null);
}

export function deployCard(pid) {
  const box = h("div", { class: "deploy-box", "data-key": "deploy:" + pid });
  const load = async () => {
    let v;
    try { v = await api("GET", "/api/projects/" + enc(pid) + "/roads"); } catch (e) { fill(box); return; }
    const may = (v.deciders || []).includes(S.persona) && v.roads.length;
    const tool = may ? button("Choose the road", { icon: "server", kind: "small", "data-control": "choose_road", key: "deploy-choose",
      onclick: () => openModal("Where this project deploys", chooseForm(pid, v, load), { icon: "server", wide: true }) })
      : h("span", { class: "muted small" }, icon("user"), v.roads.length ? " IT chooses the road." : " No road is configured yet: IT configures one in Settings.");
    const rows = v.environments.map((e) => h("li", { class: "road-row", "data-key": "deploy-env:" + e.environment },
      h("span", { class: "cat-ic" }, icon("server")),
      h("div", { class: "sig-b" }, h("b", null, e.environment + " "), h("span", { class: "muted small" }, e.road ? e.road + " (" + (KIND[e.kind] || e.kind || "?") + ")" : "no road named"),
        e.cloudrun ? h("div", { class: "sig-m" }, h("span", null, e.cloudrun.workload === "job" ? "a scheduled job" : "a service"),
          e.cloudrun.schedule ? h("span", { class: "mono" }, e.cloudrun.schedule.cron + " " + (e.cloudrun.schedule.time_zone || "")) : null) : null,
        missingList(e.missing)),
      readyChip(e)));
    fill(box, card({ title: "Where it deploys", icon: "server", id: "deploy-roads", cls: "deploy-card", tools: [tool],
      info: "Each environment of the plan and the paved road it lands on. The test environment comes first; production waits for IT's deploy gate." },
    rows.length ? h("ul", { class: "road-list" }, rows) : empty("server", "This project's maturity deploys nowhere yet."),
    jobStatus(v.job_status)));
  };
  load();
  return box;
}
