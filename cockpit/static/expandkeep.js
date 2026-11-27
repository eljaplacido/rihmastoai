/* Compact boxes stay open for review (FR-CMP2), the parts expand.js leans on. An independent check of FR-CMP1 found
   Expand on widgets that cut nothing, and the toasts of what a person did in the side panel shown under its backdrop.

     cuts(shown, whole)   true when the whole content says more than the compact box shows: more words, or more rows,
                          cards or controls. A box that cuts nothing carries no Expand.
     liftToasts(dlg)      while a modal side panel is open, the page's toasts (#status) are shown in it, so they sit in
                          the top layer above its backdrop
     dropToasts()         and go back to their place in the page when it closes (before the panel is emptied) */

import { $ } from "./core.js";

const ROWS = "li, tr, .cat-card, .card, [data-key], [data-control]";

function words(el) { return String((el && el.textContent) || "").replace(/\s+/g, " ").trim(); }
function rows(el) { return el && el.querySelectorAll ? el.querySelectorAll(ROWS).length : 0; }

export function cuts(shown, whole) {
  if (!whole) return false;
  if (!shown) return true;
  return words(whole).length > words(shown).length || rows(whole) > rows(shown);
}

let home = null;   // where the toasts live in the page: { parent, next }

export function liftToasts(dlg) {
  const region = $("#status");
  if (!region || !dlg || region.parentElement === dlg) return;
  home = { parent: region.parentElement, next: region.nextSibling };
  dlg.append(region);
}

export function dropToasts() {
  const region = $("#status");
  if (!region || !home) return;
  const { parent, next } = home;
  home = null;
  if (!parent || !parent.isConnected) { document.body.prepend(region); return; }
  parent.insertBefore(region, next && next.parentNode === parent ? next : null);
}
