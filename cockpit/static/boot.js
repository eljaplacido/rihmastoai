/* The cockpit's boot guard (FR-T1): if the page's code cannot load, the person is told, never left on a blank page.

A classic script, loaded before the module app.js. When a script of the page fails to load (a dropped or refused
connection on a busy machine), or the page finished loading and the cockpit never started, the page reloads once by
itself: an unused one-use sign-in link in the address still signs it in. If it fails again, it says so with a
Reload button. app.js marks the start (window.__rihmaBooted) and clears the retry, so the next failure retries once.
*/
(function () {
  "use strict";
  var KEY = "gf.bootRetry";
  var said = false;

  function say() {
    if (said || !document.body) return;
    said = true;
    var box = document.createElement("div");
    box.className = "boot-failed card";
    box.setAttribute("role", "alert");
    box.setAttribute("data-key", "boot-failed");
    var title = document.createElement("h1");
    title.textContent = "The cockpit didn't finish loading";
    var text = document.createElement("p");
    text.textContent = "Part of the page could not be fetched from the cockpit server (it may be busy, or stopped). "
      + "Check that python -m cockpit.server is running, then reload.";
    var again = document.createElement("button");
    again.type = "button";
    again.className = "btn primary";
    again.setAttribute("data-key", "boot-reload");
    again.textContent = "Reload";
    again.addEventListener("click", function () { location.reload(); });
    box.appendChild(title);
    box.appendChild(text);
    box.appendChild(again);
    document.body.appendChild(box);
  }

  function failed() {
    if (window.__rihmaBooted) return;
    var tried = false;
    try { tried = sessionStorage.getItem(KEY) === "1"; } catch (e) { tried = true; }
    if (!tried) {
      try { sessionStorage.setItem(KEY, "1"); } catch (e) { /* no storage: say it instead */ }
      location.reload();
      return;
    }
    say();
  }

  window.addEventListener("error", function (e) {
    var t = e && e.target;
    if (t && t.tagName === "SCRIPT") failed();
  }, true);
  window.addEventListener("load", function () { if (!window.__rihmaBooted) failed(); });
})();
