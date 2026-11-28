/* The word in force, over what the page draws (D-0027, FR-TM6): where a view names a kind of record in passing (a capsule's
   "3 requirements", a spec page's heading, the board's filter, a graph line) it says the word the team or the project gave
   it. The owner asked for the word wherever a kind's name appears, so this reads the page's text once it is drawn and
   says each shipped kind name in the word in force (words.js sayWords, the same rows the kernel's kernel/vocab_say.py reads).

   What people wrote is never reworded: an element marked data-ud (a title, a brief, a finding) and what is code, a field
   or a script are left alone, and so is anything marked data-said (the Vocabulary views, which show both words side by
   side, and the assistant's answers, which the kernel already said in the words in force). A text node is said once:
   what this wrote is remembered, so a team that says "task" for one kind and "story" for another is not read twice. Nothing
   stored is changed: only how the page reads. */

import { sayWords, hasWords } from "./words.js";

const TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "CODE", "PRE", "SVG"]);
const ATTRS = ["placeholder", "title", "aria-label"];
const done = new WeakMap();        // a text node, or an element's attribute, to what this wrote there
let busy = false;

/* Whether an element sits in what is left alone: people's own text, code, fields, marked areas. */
function left(el) {
  for (let e = el; e; e = e.parentElement) {
    if (TAGS.has(e.tagName.toUpperCase()) || e.hasAttribute("data-ud") || e.hasAttribute("data-said") || e.isContentEditable) return true;
  }
  return false;
}

function fixText(node) {
  if (!node.isConnected || done.get(node) === node.nodeValue || !node.parentElement || left(node.parentElement)) return;
  const said = sayWords(node.nodeValue);
  if (said !== node.nodeValue) node.nodeValue = said;
  done.set(node, node.nodeValue);
}

function fixAttrs(el) {
  for (const a of ATTRS) {
    const key = done.get(el) || {};
    const v = el.getAttribute(a);
    if (v === null || key[a] === v || left(el)) continue;
    const said = sayWords(v);
    if (said !== v) el.setAttribute(a, said);
    done.set(el, Object.assign(key, { [a]: said }));
  }
}

/* Say every text and label under ``root`` (or ``root`` itself) in the word in force. */
export function applyWords(root) {
  if (!root || !hasWords()) return;
  if (root.nodeType === 3) { fixText(root); return; }
  if (root.nodeType !== 1 || left(root)) return;
  const texts = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const found = [];
  for (let n = texts.nextNode(); n; n = texts.nextNode()) found.push(n);
  found.forEach(fixText);
  fixAttrs(root);
  root.querySelectorAll("[placeholder],[title],[aria-label]").forEach(fixAttrs);
}

/* Watch the page: whatever is drawn after this is said in the word in force as it appears. */
export function wireWords(root) {
  const watch = new MutationObserver((records) => {
    if (busy || !hasWords()) return;
    busy = true;
    try {
      for (const r of records) {
        if (r.type === "childList") r.addedNodes.forEach(applyWords);
        else if (r.type === "characterData") fixText(r.target);
      }
    } finally { busy = false; }
  });
  watch.observe(root, { childList: true, subtree: true, characterData: true });
  applyWords(root);
  return watch;
}
