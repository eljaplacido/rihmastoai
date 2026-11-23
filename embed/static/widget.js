/* Rihma embed widget: a small chat a website includes with one script tag.
 *
 *   <script src="https://feedback.example/e/E-001/widget.js" data-rihma-embed="E-001"
 *           data-key="rk_..." data-endpoint="https://feedback.example" data-lang="en" defer></script>
 *
 * It lives in a shadow root, needs no other files, sends only what the person types, and keeps the
 * conversation in this tab's sessionStorage. Text is always inserted as text, never as HTML.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script) return;
  var embedId = script.getAttribute("data-rihma-embed");
  var key = script.getAttribute("data-key");
  var endpoint = (script.getAttribute("data-endpoint") || "").replace(/\/+$/, "");
  if (!embedId || !key || !endpoint) return;
  var lang = (script.getAttribute("data-lang") || navigator.language || "en").slice(0, 2).toLowerCase();
  var T = {
    en: { open: "Give feedback", title: "Tell us what you saw", hint: "What did you try, and what happened?",
          send: "Send", close: "Close", sending: "Sending…", error: "That did not go through. Please try again.",
          filed: "Passed on to the team", privacy: "Only what you write here is sent." },
    fi: { open: "Anna palautetta", title: "Kerro mitä huomasit", hint: "Mitä yritit tehdä, ja mitä tapahtui?",
          send: "Lähetä", close: "Sulje", sending: "Lähetetään…", error: "Lähetys ei onnistunut. Yritä uudelleen.",
          filed: "Välitetty tiimille", privacy: "Vain tähän kirjoittamasi lähetetään." }
  }[lang === "fi" ? "fi" : "en"];
  var storeKey = "rihma-embed-" + embedId;
  var history = [];
  try { history = JSON.parse(sessionStorage.getItem(storeKey) || "[]"); } catch (e) { history = []; }

  var host = document.createElement("div");
  host.setAttribute("data-rihma-embed-host", embedId);
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  var css =
    ":host{all:initial}" +
    ".btn{position:fixed;right:20px;bottom:20px;z-index:2147483000;font:600 14px/1 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;" +
    "background:#1c1917;color:#fafaf9;border:1px solid #44403c;border-radius:999px;padding:12px 18px;cursor:pointer;box-shadow:0 1px 2px rgba(28,25,23,.12),0 4px 12px rgba(28,25,23,.12)}" +
    ".btn:focus-visible,.send:focus-visible,.x:focus-visible,textarea:focus-visible{outline:2px solid #d97706;outline-offset:2px}" +
    ".panel{position:fixed;right:20px;bottom:76px;z-index:2147483000;width:min(360px,calc(100vw - 40px));max-height:min(520px,calc(100vh - 120px));" +
    "display:flex;flex-direction:column;background:#fff;color:#1c1917;border:1px solid #e7e5e4;border-radius:16px;overflow:hidden;" +
    "font:14px/1.45 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;box-shadow:0 1px 2px rgba(28,25,23,.08),0 8px 24px rgba(28,25,23,.12)}" +
    ".panel[hidden]{display:none}" +
    ".head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #e7e5e4;font-weight:600}" +
    ".x{background:none;border:0;font-size:18px;cursor:pointer;color:#57534e;border-radius:6px;padding:2px 8px}" +
    ".log{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:8px}" +
    ".m{max-width:85%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word}" +
    ".person{align-self:flex-end;background:#1c1917;color:#fafaf9}" +
    ".assistant{align-self:flex-start;background:#f5f5f4}" +
    ".note{align-self:center;font-size:12px;color:#57534e}" +
    ".form{display:flex;gap:8px;padding:10px;border-top:1px solid #e7e5e4}" +
    "textarea{flex:1;resize:none;height:56px;font:inherit;border:1px solid #d6d3d1;border-radius:10px;padding:8px}" +
    ".send{background:#d97706;color:#1c1917;font-weight:600;border:0;border-radius:10px;padding:0 14px;cursor:pointer}" +
    ".send[disabled]{opacity:.6;cursor:default}" +
    ".foot{font-size:11px;color:#78716c;padding:0 14px 10px}" +
    "@media (prefers-color-scheme:dark){.panel{background:#1c1917;color:#f5f5f4;border-color:#44403c}" +
    ".head,.form{border-color:#44403c}.assistant{background:#292524}.x{color:#d6d3d1}" +
    "textarea{background:#0c0a09;color:#f5f5f4;border-color:#57534e}.note,.foot{color:#a8a29e}}" +
    "@media (prefers-reduced-motion:no-preference){.panel{transition:opacity .18s ease-out}}";
  try {
    var sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    root.adoptedStyleSheets = [sheet];
  } catch (e) {
    var style = document.createElement("style");
    style.textContent = css;
    root.appendChild(style);
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  var btn = el("button", "btn", T.open);
  btn.type = "button";
  btn.setAttribute("aria-expanded", "false");
  var panel = el("div", "panel");
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", T.title);
  var head = el("div", "head", T.title);
  var x = el("button", "x", "×");
  x.type = "button";
  x.setAttribute("aria-label", T.close);
  head.appendChild(x);
  var log = el("div", "log");
  log.setAttribute("aria-live", "polite");
  var form = el("form", "form");
  var input = el("textarea");
  input.setAttribute("aria-label", T.hint);
  input.placeholder = T.hint;
  input.maxLength = 2000;
  var send = el("button", "send", T.send);
  send.type = "submit";
  form.appendChild(input);
  form.appendChild(send);
  var foot = el("div", "foot", T.privacy);
  panel.appendChild(head);
  panel.appendChild(log);
  panel.appendChild(form);
  panel.appendChild(foot);
  root.appendChild(panel);
  root.appendChild(btn);

  function save() {
    try { sessionStorage.setItem(storeKey, JSON.stringify(history.slice(-12))); } catch (e) { /* private mode */ }
  }
  function add(role, text) {
    log.appendChild(el("div", "m " + role, text));
    log.scrollTop = log.scrollHeight;
  }
  history.forEach(function (m) { add(m.role, m.text); });
  function toggle(open) {
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) input.focus(); else btn.focus();
  }
  btn.addEventListener("click", function () { toggle(panel.hidden); });
  x.addEventListener("click", function () { toggle(false); });
  root.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) toggle(false); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || send.disabled) return;
    history.push({ role: "person", text: text });
    add("person", text);
    input.value = "";
    send.disabled = true;
    send.textContent = T.sending;
    fetch(endpoint + "/e/" + encodeURIComponent(embedId) + "/messages", {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "omit",
      body: JSON.stringify({ key: key, history: history })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.j && res.j.error);
        if (res.j.reply) { history.push({ role: "assistant", text: res.j.reply }); add("assistant", res.j.reply); }
        if (res.j.filed) { add("note", T.filed + " (" + res.j.filed.ref + ")"); history = []; }
        save();
      })
      .catch(function () { history.pop(); add("note", T.error); save(); })
      .then(function () { send.disabled = false; send.textContent = T.send; });
  });
})();
