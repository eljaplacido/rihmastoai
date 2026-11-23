/* Rihma embed widget: a small chat a website includes with one script tag.
 *
 *   <script src="https://feedback.example/e/E-001/widget.js" data-rihma-embed="E-001"
 *           data-key="rk_..." data-endpoint="https://feedback.example" data-kind="feedback"
 *           data-lang="en" defer></script>
 *
 * data-kind is "feedback" (the default) or "need", and sets the wording. data-lang is "en" or "fi"
 * and defaults to the browser's language.
 *
 * It lives in a shadow root, needs no other files, sends only what the person types, and keeps the
 * conversation in this tab's sessionStorage. Text is always inserted as text, never as HTML. It never
 * shows the visitor the project's own card or signal number. A message that does not go through stays
 * in the box, with the reason.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script) return;
  var embedId = script.getAttribute("data-rihma-embed");
  var key = script.getAttribute("data-key");
  var endpoint = (script.getAttribute("data-endpoint") || "").replace(/\/+$/, "");
  if (!embedId || !key || !endpoint) return;
  var lang = (script.getAttribute("data-lang") || navigator.language || "en").slice(0, 2).toLowerCase() === "fi" ? "fi" : "en";
  var kind = script.getAttribute("data-kind") === "need" ? "need" : "feedback";
  var MAX_SENT = 8;          // the server reads at most the last 4 exchanges
  // The server's fixed reply when no model answers (kernel.embeds.THANKS), said here in the widget's language.
  var SERVER_THANKS = "Thank you. It has been passed on to the team.";
  var T = {
    en: {
      feedback: { open: "Give feedback", title: "Tell us what you saw", hint: "What did you try, and what happened?" },
      need: { open: "Share a need", title: "Tell us what you need", hint: "What would help you, and why?" },
      send: "Send", close: "Close", sending: "Sending…", thanks: SERVER_THANKS,
      filed: "Sent to the team. What you write next starts a new message.",
      privacy: "Only what you write here is sent.",
      kept: "Your message is still in the box.",
      rate: "Too many messages reached this chat just now. Wait a minute, then send again.",
      key: "This chat is not set up correctly on this website, so it cannot take messages.",
      closed: "This chat is not taking messages on this website.",
      unread: "The chat could not read that message.",
      busy: "The chat is busy. Please try again in a moment.",
      down: "The chat is not available just now. Please try again later.",
      unreachable: "The chat could not be reached. It may be closed, or the connection is down."
    },
    fi: {
      feedback: { open: "Anna palautetta", title: "Kerro, mitä huomasit", hint: "Mitä yritit tehdä ja mitä tapahtui?" },
      need: { open: "Kerro tarpeesta", title: "Kerro, mitä tarvitset", hint: "Mikä auttaisi sinua, ja miksi?" },
      send: "Lähetä", close: "Sulje", sending: "Lähetetään…", thanks: "Kiitos. Viestisi on välitetty tiimille.",
      filed: "Lähetetty tiimille. Seuraava viestisi aloittaa uuden keskustelun.",
      privacy: "Vain tähän kirjoittamasi lähetetään.",
      kept: "Viestisi on yhä kirjoituskentässä.",
      rate: "Tähän chattiin tuli juuri liikaa viestejä. Odota minuutti ja lähetä sitten uudelleen.",
      key: "Tätä chattia ei ole otettu oikein käyttöön tällä sivustolla, joten se ei voi ottaa viestejä vastaan.",
      closed: "Tämä chat ei ota vastaan viestejä tällä sivustolla.",
      unread: "Chat ei pystynyt lukemaan viestiä.",
      busy: "Chat on varattu. Yritä hetken kuluttua uudelleen.",
      down: "Chat ei ole juuri nyt käytettävissä. Yritä myöhemmin uudelleen.",
      unreachable: "Chattiin ei saatu yhteyttä. Se voi olla suljettu, tai yhteys on poikki."
    }
  }[lang];
  var W = T[kind];
  var storeKey = "rihma-embed-" + embedId;
  var history = [];
  try { history = JSON.parse(sessionStorage.getItem(storeKey) || "[]"); } catch (e) { history = []; }
  if (!Array.isArray(history)) history = [];
  history = history.filter(function (m) {
    return m && (m.role === "person" || m.role === "assistant") && typeof m.text === "string";
  });

  var host = document.createElement("div");
  host.setAttribute("data-rihma-embed-host", embedId);
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  var font = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif";
  var css =
    ":host{all:initial}" +
    ".btn{position:fixed;right:20px;bottom:20px;z-index:2147483000;font:600 14px/1 " + font + ";" +
    "background:#1c1917;color:#fafaf9;border:1px solid #44403c;border-radius:999px;padding:12px 18px;cursor:pointer;" +
    "box-shadow:0 1px 2px rgba(28,25,23,.12),0 4px 12px rgba(28,25,23,.12)}" +
    // The launcher sits on any website: a ring of the panel's colour in the offset keeps its focus ring visible.
    ".btn:focus-visible{outline:2px solid #b45309;outline-offset:2px;box-shadow:0 0 0 2px #fff}" +
    ".send:focus-visible,.x:focus-visible,textarea:focus-visible{outline:2px solid #b45309;outline-offset:2px}" +
    ".panel{position:fixed;right:20px;bottom:76px;z-index:2147483000;width:min(360px,calc(100vw - 40px));" +
    "max-height:min(520px,calc(100vh - 120px));display:flex;flex-direction:column;background:#fff;color:#1c1917;" +
    "border:1px solid #e7e5e4;border-radius:16px;overflow:hidden;box-sizing:border-box;color-scheme:light;" +
    "font:14px/1.45 " + font + ";box-shadow:0 1px 2px rgba(28,25,23,.08),0 8px 24px rgba(28,25,23,.12)}" +
    ".panel[hidden]{display:none}" +
    ".head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px;" +
    "border-bottom:1px solid #e7e5e4;font-weight:600}" +
    ".x{background:none;border:0;font-size:18px;line-height:1;cursor:pointer;color:#57534e;border-radius:6px;padding:4px 8px}" +
    ".log{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:8px}" +
    ".m{max-width:85%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere}" +
    ".person{align-self:flex-end;background:#1c1917;color:#fafaf9}" +
    ".assistant{align-self:flex-start;background:#f5f5f4}" +
    ".note{align-self:center;max-width:100%;font-size:12px;color:#57534e;text-align:center}" +
    ".note.err{color:#b91c1c}" +
    ".form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 8px;padding:10px;border-top:1px solid #e7e5e4}" +
    ".label{grid-column:1/-1;font-size:12px;font-weight:600;color:#44403c}" +
    "textarea{box-sizing:border-box;width:100%;resize:none;height:56px;font:inherit;color:inherit;background:#fff;" +
    "border:1px solid #78716c;border-radius:10px;padding:8px}" +
    ".send{background:#d97706;color:#1c1917;font:inherit;font-weight:600;border:0;border-radius:10px;padding:0 14px;cursor:pointer}" +
    ".send[aria-disabled=true]{opacity:.6;cursor:default}" +
    ".foot{font-size:11px;color:#78716c;padding:0 14px 10px}" +
    "@media (prefers-color-scheme:dark){.panel{background:#1c1917;color:#f5f5f4;border-color:#44403c;color-scheme:dark}" +
    ".head,.form{border-color:#44403c}.assistant{background:#292524}.person{background:#e7e5e4;color:#1c1917}" +
    ".x{color:#d6d3d1}.label{color:#d6d3d1}textarea{background:#0c0a09;color:#f5f5f4;border-color:#78716c}" +
    ".note,.foot{color:#a8a29e}.note.err{color:#fca5a5}" +
    ".send:focus-visible,.x:focus-visible,textarea:focus-visible{outline-color:#f59e0b}" +
    ".btn:focus-visible{outline-color:#f59e0b;box-shadow:0 0 0 2px #1c1917}}";
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
  var btn = el("button", "btn", W.open);
  btn.type = "button";
  btn.lang = lang;
  btn.setAttribute("aria-expanded", "false");
  btn.setAttribute("aria-controls", "rihma-panel");
  var panel = el("div", "panel");
  panel.id = "rihma-panel";
  panel.lang = lang;
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-labelledby", "rihma-title");
  var head = el("div", "head");
  var title = el("span", null, W.title);
  title.id = "rihma-title";
  var x = el("button", "x", "×");
  x.type = "button";
  x.setAttribute("aria-label", T.close);
  head.appendChild(title);
  head.appendChild(x);
  var log = el("div", "log");
  log.setAttribute("role", "log");
  log.setAttribute("aria-live", "polite");
  var form = el("form", "form");
  var label = el("label", "label", W.hint);
  label.htmlFor = "rihma-message";
  var input = el("textarea");
  input.id = "rihma-message";
  input.maxLength = 2000;
  input.setAttribute("aria-describedby", "rihma-privacy");
  var send = el("button", "send", T.send);
  send.type = "submit";
  send.setAttribute("aria-disabled", "false");
  form.appendChild(label);
  form.appendChild(input);
  form.appendChild(send);
  var foot = el("div", "foot", T.privacy);
  foot.id = "rihma-privacy";
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
    var n = log.appendChild(el("div", "m " + role, text));
    log.scrollTop = log.scrollHeight;
    return n;
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
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });

  // Why a send did not go through, in words for the visitor: from the answer's status, never its raw text.
  function reason(status, error) {
    if (status === 429) return T.rate;
    if (status === 403) return /wrong key/.test(error) ? T.key : T.closed;
    if (status === 400 || status === 413) return T.unread;
    if (status === 503) return T.busy;
    if (status) return T.down;
    return T.unreachable;        // no answer the page may read: offline, or the chat is closed to this site
  }
  var busy = false;
  function setBusy(on) {
    busy = on;
    send.setAttribute("aria-disabled", String(on));   // not disabled: a focused button keeps the focus
    send.textContent = on ? T.sending : T.send;
    log.setAttribute("aria-busy", String(on));
  }
  // After a send, the focus goes back to the box for the next message, unless the person moved it elsewhere.
  function refocus() {
    var at = root.activeElement;
    if (!panel.hidden && (at === send || (!at && document.activeElement === document.body))) input.focus();
  }
  // A refusal stays in sight, tied to the box that holds the message, until the next send.
  var refusal = null;
  function refuse(words) {
    clearRefusal();
    refusal = add("note err", words);
    refusal.id = "rihma-refusal";
    input.setAttribute("aria-describedby", "rihma-refusal rihma-privacy");
  }
  function clearRefusal() {
    if (refusal && refusal.parentNode) refusal.parentNode.removeChild(refusal);
    refusal = null;
    input.setAttribute("aria-describedby", "rihma-privacy");
  }
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;
    clearRefusal();
    var before = history.length;
    var bubble = add("person", text);
    history.push({ role: "person", text: text });
    input.value = "";
    setBusy(true);
    var status = 0;
    fetch(endpoint + "/e/" + encodeURIComponent(embedId) + "/messages", {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "omit",
      body: JSON.stringify({ key: key, history: history.slice(-MAX_SENT) })
    }).then(function (r) {
      status = r.status;
      return r.text().then(function (t) {
        var j = null;
        try { j = JSON.parse(t); } catch (x) { j = null; }
        if (!r.ok || !j || typeof j !== "object") throw new Error((j && typeof j.error === "string") ? j.error : "");
        return j;
      });
    }).then(function (j) {
      var reply = typeof j.reply === "string" ? j.reply : "";
      if (reply === SERVER_THANKS) reply = T.thanks;
      if (reply) { history.push({ role: "assistant", text: reply }); add("assistant", reply); }
      if (j.filed) { add("note", T.filed); history = []; }   // the visitor never sees the project's own number
      save();
    }, function (err) {
      history.splice(before);
      log.removeChild(bubble);                                // it was not sent: no bubble says it was
      input.value = input.value ? text + "\n" + input.value : text;
      refuse(reason(status, String((err && err.message) || "")) + " " + T.kept);
      save();
    }).then(finish, finish);
  });
  function finish() { setBusy(false); refocus(); }
})();
