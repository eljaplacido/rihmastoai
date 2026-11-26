/* The reviewer's page (kernel/hitl_page.py, FR-HITL1): a person outside the system answers the questions put to
   them. The link's token sits after "#", so no server, log or link preview receives it; it is exchanged once for a
   session kept in this tab only, and the address is cleaned at once. Everything shown is text from the server,
   set as text, never as markup. */
(function () {
  "use strict";
  var KEY = "rihma.reviewer.session";
  var main = document.getElementById("main");

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] === null || attrs[k] === undefined || attrs[k] === false) return;
      if (k === "text") e.textContent = attrs[k]; else e.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    });
    (kids || []).forEach(function (k) { if (k) e.appendChild(typeof k === "string" ? document.createTextNode(k) : k); });
    return e;
  }
  function show() {
    var kids = [];
    Array.prototype.slice.call(arguments).forEach(function (k) { kids = kids.concat(Array.isArray(k) ? k : [k]); });
    main.replaceChildren.apply(main, kids.filter(Boolean));
  }
  function store(v) { try { if (v) sessionStorage.setItem(KEY, v); else sessionStorage.removeItem(KEY); } catch (e) { /* private mode */ } }
  function stored() { try { return sessionStorage.getItem(KEY); } catch (e) { return null; } }

  function call(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
      credentials: "omit", referrerPolicy: "no-referrer", body: JSON.stringify(body) })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) throw new Error(data.error || "Something went wrong. Try again in a moment.");
          return data;
        });
      });
  }

  function refused(message) {
    store(null);
    show(el("h1", { text: "Your questions" }), el("p", { class: "err", role: "alert", text: message }),
      el("p", { class: "muted small", text: "Nothing you answered before is lost: each answer was saved when you sent it." }));
  }

  function when(iso) {
    var t = Date.parse(iso);
    return isNaN(t) ? iso : new Date(t).toLocaleString();
  }

  function answerForm(item, session) {
    var form = el("form", { "aria-label": "Answer " + item.id });
    var pickId = "pick-" + item.id;
    if (item.kind === "decision") {
      var set = el("fieldset", { class: "opts" }, [el("legend", { class: "f", text: "Your choice" })]);
      item.options.forEach(function (o, i) {
        var id = pickId + "-" + i;
        set.appendChild(el("label", { for: id }, [el("input", { type: "radio", name: pickId, id: id, value: o, required: true }),
          el("span", { text: o })]));
      });
      form.appendChild(set);
    } else {
      form.appendChild(el("label", { class: "f", for: pickId, text: item.kind === "feedback" ? "Your feedback" : "Your answer" }));
      form.appendChild(el("textarea", { id: pickId, required: true, maxlength: "2000" }));
    }
    var noteId = "note-" + item.id;
    if (item.kind === "decision") {
      form.appendChild(el("label", { class: "f", for: noteId, text: "Anything to add (optional)" }));
      form.appendChild(el("textarea", { id: noteId, maxlength: "2000" }));
    }
    var msg = el("p", { class: "small", role: "status" });
    var send = el("button", { type: "submit", text: "Send my answer" });
    form.appendChild(send);
    form.appendChild(msg);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var chosen = item.kind === "decision" ? form.querySelector("input[name='" + pickId + "']:checked") : form.querySelector("#" + pickId);
      var note = form.querySelector("#" + noteId);
      if (!chosen || !String(chosen.value).trim()) { msg.className = "small err"; msg.textContent = "Write or choose your answer first."; return; }
      send.disabled = true;
      msg.className = "small muted";
      msg.textContent = "Sending…";
      call("/r/api/answer", { session: session, ask: item.id, answer: chosen.value, comment: note ? note.value : "" })
        .then(function (view) { draw(view, session); })
        .catch(function (e) { send.disabled = false; msg.className = "small err"; msg.textContent = e.message; });
    });
    return form;
  }

  function card(item, session) {
    var tags = el("div", null, [el("span", { class: "tag", text: item.family_label }), el("span", { class: "tag", text: item.kind.charAt(0).toUpperCase() + item.kind.slice(1) })]);
    var body = [tags, el("h2", { text: item.text }), el("p", { class: "muted small", text: "Asked by " + item.asked_by })];
    if (item.state === "open") body.push(answerForm(item, session));
    else body.push(el("p", { class: "done", text: item.answer ? "Answered: " + item.answer : "Answered. Thank you." }));
    return el("section", { class: "item", "data-ask": item.id }, body);
  }

  function draw(view, session) {
    var who = el("p", { class: "who muted" }, [
      "You answer as ", el("strong", { text: view.name }), view.role ? " (" + view.role + ")" : "",
      ". Your answers are recorded with your name. ", el("span", { class: "small", text: "Open until " + when(view.expires) + "." })]);
    var lead = view.open ? (view.open === 1 ? "One question waits for you" : view.open + " questions wait for you")
      : "Everything is answered. Thank you: you can close this page.";
    show(el("h1", { text: "Your questions" + (view.context ? ": " + view.context : "") }), who,
      el("p", { class: "note", text: lead + (view.open ? ", from " + view.from + "." : "") }),
      view.items.length ? null : el("p", { class: "muted", text: "No questions are on this link any more. Ask " + view.from + " if you expected some." }),
      view.items.map(function (i) { return card(i, session); }));
  }

  function load(session) {
    return call("/r/api/items", { session: session }).then(function (view) { draw(view, session); });
  }

  function start() {
    var token = location.hash.replace(/^#/, "");
    if (token) {
      history.replaceState(null, "", location.pathname);   // the token leaves the address bar at once
      call("/r/api/open", { link: token })
        .then(function (out) { store(out.session); return load(out.session); })
        .catch(function (e) { refused(e.message); });
      return;
    }
    var session = stored();
    if (!session) { refused("Open the link you were sent to see your questions. A link opens once."); return; }
    load(session).catch(function (e) { refused(e.message); });
  }
  start();
}());
