/* Agent operations' Prices card (kernel/agentops_prices.py, FR-AOP2): every model the runs name with its price per
   million tokens, and Price a model, so "cost not measured" turns into a figure without editing any file. A model
   that runs on the person's own machine is marked local: no API money. Signed; Ask Rihma does the same ("set the
   price of <model> to <in> and <out> per million tokens", "mark <model> as local"). */

import { h, icon, chip, api, card, button, say, plural, signed, needPerson, act, num, ago, mayAct } from "./core.js";
import { dataTable } from "./charts.js";
import { pick, emptyState, datum } from "./words.js";

const per = (v, cur) => (v === null || v === undefined ? null : v + " " + cur);

function priceOf(m, cur) {
  if (m.local) return chip("good", "cpu", pick("On your own machine", "Local"));
  if (!m.priced && m.unpriced) return chip("warning", "alert", "Not priced");
  if (!m.priced) return chip("neutral", "check", pick("Cost recorded with each use", "Priced when recorded"));
  return h("span", { class: "mono" }, per(m.input, cur) + " in · " + per(m.output, cur) + " out" + (m.cached !== null && m.cached !== undefined ? " · " + per(m.cached, cur) + " cached" : ""));
}

function form(d, redraw) {
  const p = d.pricing;
  const may = mayAct(p.who);
  const first = (p.models.find((m) => !m.priced && m.unpriced > (m.no_tokens || 0)) || p.models.find((m) => m.unpriced) || {}).model || "";
  const model = h("input", { id: "aop-pr-model", type: "text", value: first, list: "aop-pr-models", autocomplete: "off", "data-key": "aop-pr:model", "data-ud": "" });
  const known = h("datalist", { id: "aop-pr-models" }, p.models.map((m) => h("option", { value: m.model })));
  const amount = (id, label) => h("div", { class: "field aop-pr-n" }, h("label", { for: id }, label),
    h("input", { id, type: "number", min: "0", step: "any", inputmode: "decimal", "data-key": id }));
  const inp = amount("aop-pr-in", "In, " + p.currency + " per million tokens");
  const out = amount("aop-pr-out", "Out, " + p.currency + " per million tokens");
  const cached = amount("aop-pr-cached", pick("Reused text (optional)", "Cached in (optional)"));
  const localBox = h("input", { type: "checkbox", id: "aop-pr-local", "data-key": "aop-pr:local" });
  localBox.addEventListener("change", () => [inp, out, cached].forEach((f) => { f.querySelector("input").disabled = localBox.checked || null; }));
  const val = (f) => f.querySelector("input").value.trim();
  const save = button("Price the model", { icon: "check", kind: "small primary", key: "aop-pr:save", "data-control": "agent_ops_price", disabled: !may || null,
    onclick: () => act(save.parentNode, async () => {
      if (!needPerson()) return;
      const body = localBox.checked ? { model: model.value.trim(), local: true }
        : { model: model.value.trim(), input: val(inp), output: val(out), cached: val(cached) || null };
      const got = await api("POST", "/api/agent-ops/prices", Object.assign(body, signed()));
      say(got.price.local ? got.model + " is marked as running on your own machine, signed and recorded."
        : got.model + " is priced at " + got.price.input + " in and " + got.price.output + " out per million tokens, signed and recorded.", "good");
      redraw();
    }) });
  return h("div", { class: "aop-pr-form" }, h("div", { class: "field" }, h("label", { for: "aop-pr-model" }, "Model"), model, known),
    h("div", { class: "aop-pr-row" }, inp, out, cached),
    h("div", { class: "set-row" }, h("label", { class: "chk-l", for: "aop-pr-local" }, localBox, " ", pick("It runs on our own machine (no API cost)", "Local model (no API cost)"))),
    h("div", { class: "btns" }, save, may ? null : h("span", { class: "small muted" }, icon("user"), " An AI architect, developer, IT, operations or the business owner prices a model.")));
}

// What keeps a cost unmeasured: a model with no price, or runs that recorded no tokens (no price helps them), each
// said apart, so pricing a model is never read as having failed (FR-AOP3).
function lede(p) {
  const waits = (m) => (m.priced ? 0 : m.unpriced - (m.no_tokens || 0));
  const unpriced = p.models.filter((m) => waits(m) > 0);
  const blind = p.models.reduce((a, m) => a + (m.no_tokens || 0), 0);
  const lines = [];
  if (unpriced.length) lines.push(h("p", { class: "small", "data-lede": "unpriced" }, icon("alert"), " ", plural(unpriced.length, "model") + " without a price: the cost of " +
    plural(unpriced.reduce((a, m) => a + waits(m), 0), "run") + " is not measured until " + (unpriced.length > 1 ? "they are" : "it is") + " priced."));
  if (blind) lines.push(h("p", { class: "small", "data-lede": "no-tokens" }, icon("info"), " ", plural(blind, "run") + pick(" recorded no amount of text used", " recorded no token counts") +
    ", so " + (blind > 1 ? "their" : "its") + " cost is not measured whatever the price" + pick(".", ": a price turns tokens into cost.")));
  if (!lines.length) lines.push(h("p", { class: "small" }, p.models.length ? pick("Every AI model in use has a price.", "Every model the runs name has a price.") : ""));
  return lines;
}

export function pricesCard(d, redraw) {
  const p = d.pricing;
  const lines = lede(p);
  const table = p.models.length ? dataTable([{ label: "Model", value: (m) => h("span", { class: "mono aop-pr-m", "data-ud": "" }, m.model) }, { label: "Price per million tokens", value: (m) => priceOf(m, p.currency) },
    { label: "Runs", num: true, value: (m) => num(m.runs) }, { label: "Not priced", num: true, value: (m) => num(m.unpriced) },
    { label: "Set by", value: (m) => (m.set_by ? h("span", null, datum(m.set_by), " · " + ago(m.set_on)) : "") }], p.models, "Model prices")
    : emptyState("agentops_prices", null, { icon: "coins" });
  return card({ title: pick("What each AI model costs", "Model prices"), icon: "coins", id: "aop-prices",
    info: pick("The price of each AI model per million tokens (a token is about three quarters of a word). With a price, what the helpers cost is measured; a model on your own machine costs no API money.",
      "Price per million tokens in, out and cached for each model the runs name. A run recorded without a price is priced from this table when it is read; a harness's own reported cost is kept. Set here or by Ask Rihma; signed, recorded in Rihmasto's ledger.") },
  lines, table, form(d, redraw));
}
