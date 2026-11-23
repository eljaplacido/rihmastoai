"""The paved road's design system, ready for agents (after Meta's Astryx idea of an agent cheat sheet).

Every product gets `app/static/product.css` (tokens and a few accessible components, light and
dark, in three looks) and `factory/DESIGN.md`. The cheat sheet tells a builder cell how to make
a screen with `page()` and the classes. Builders read it; they do not edit it (`factory/` is
outside their write scope). The look is asked once, at intake, and kept in `factory/look.json`.
"""

from __future__ import annotations

LOOKS = ("neutral", "warm", "night")

PRODUCT_CSS = """/* The product's design system. Built by Rihma on the paved road; do not edit by hand.
   Looks: neutral (default), warm, night. Each has light and dark values; night is dark only. */
:root, [data-look="neutral"] {
  --bg:#f7f7f5; --surface:#ffffff; --ink:#1d1e1c; --ink-2:#4a4c47; --muted:#686a64;
  --line:#dcddd8; --accent:#2f5d8a; --accent-ink:#ffffff; --ok:#2c6a3a; --warn:#8a5800; --crit:#a3372b;
  --radius:6px; --font:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Mono",Menlo,Consolas,monospace; color-scheme: light;
}
[data-look="warm"] { --bg:#f6f1e8; --surface:#fffdf8; --ink:#2a2118; --ink-2:#55473a; --muted:#6e6152;
  --line:#e2d7c6; --accent:#9a4a1c; --accent-ink:#ffffff; }
@media (prefers-color-scheme: dark) {
  [data-look="neutral"] { --bg:#131412; --surface:#1b1c1a; --ink:#ecece8; --ink-2:#c3c4bf; --muted:#9b9c97;
    --line:#2e302c; --accent:#8fb6e0; --accent-ink:#0d1620; --ok:#8fcb9b; --warn:#e9b04f; --crit:#f2958a; color-scheme: dark; }
  [data-look="warm"] { --bg:#16120d; --surface:#1f1a14; --ink:#f1e9dd; --ink-2:#cdbfae; --muted:#a39483;
    --line:#352c22; --accent:#e8a176; --accent-ink:#1d0f06; --ok:#8fcb9b; --warn:#e9b04f; --crit:#f2958a; color-scheme: dark; }
}
[data-look="night"] { --bg:#0e1013; --surface:#161a1f; --ink:#e7eaee; --ink-2:#bcc3cc; --muted:#8f98a3;
  --line:#262c33; --accent:#7fc4c9; --accent-ink:#06191a; --ok:#8fcb9b; --warn:#e9b04f; --crit:#f2958a; color-scheme: dark; }

*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 400 16px/1.55 var(--font); }
a { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.bar { display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: center; justify-content: space-between;
  padding: 12px max(16px, 4vw); background: var(--surface); border-bottom: 1px solid var(--line); }
.bar .name { font-weight: 600; }
.bar nav { display: flex; flex-wrap: wrap; gap: 14px; }
.page { max-width: 1040px; margin: 0 auto; padding: 24px max(16px, 4vw) 48px; display: grid; gap: 20px; }
h1, h2, h3 { margin: 0; line-height: 1.25; }
h1 { font-size: 1.75rem; } h2 { font-size: 1.3rem; } h3 { font-size: 1.05rem; }
p { margin: 0; max-width: 70ch; color: var(--ink-2); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; display: grid; gap: 10px; }
.stack { display: grid; gap: 12px; }
.row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
table.data { border-collapse: collapse; width: 100%; font-size: .95rem; }
table.data th, table.data td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
table.data th { font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
table.data tr:last-child td { border-bottom: 0; }
table.data td.num { text-align: right; font-variant-numeric: tabular-nums; }
form.form { display: grid; gap: 14px; max-width: 520px; }
.field { display: grid; gap: 6px; }
.field label { font-weight: 600; font-size: .92rem; }
.field input, .field select, .field textarea { font: inherit; color: var(--ink); background: var(--surface);
  border: 1px solid var(--line); border-radius: var(--radius); padding: 9px 11px; }
.field .hint { font-size: .85rem; color: var(--muted); }
.field .error { font-size: .85rem; color: var(--crit); }
.button { font: inherit; font-weight: 600; border: 1px solid var(--accent); background: var(--accent); color: var(--accent-ink);
  border-radius: var(--radius); padding: 9px 16px; cursor: pointer; text-decoration: none; display: inline-block; }
.button.secondary { background: transparent; color: var(--accent); }
.badge { display: inline-block; font-size: .78rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; }
.badge.ok { color: var(--ok); } .badge.warn { color: var(--warn); } .badge.crit { color: var(--crit); }
.empty { border: 1px dashed var(--line); border-radius: var(--radius); padding: 28px 20px; text-align: center; display: grid; gap: 8px; justify-items: center; }
.empty p { color: var(--muted); }
.notice { border-left: 3px solid var(--accent); background: var(--surface); padding: 10px 14px; border-radius: 0 var(--radius) var(--radius) 0; }
.notice.crit { border-color: var(--crit); }
.muted { color: var(--muted); }
.mono { font-family: var(--mono); font-size: .9em; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
"""

DESIGN_MD = """# The product's design system (read this before building any screen)

Built by Rihma on the paved road. You may read this file; you may not edit it or
`app/static/product.css`. Every screen uses them, so the product looks like one product.

## Make a page

```python
from app.server import esc, page, route

@route("GET", "/")
def home(req):
    rows = "".join(f"<tr><td>{esc(i['name'])}</td><td class='num'>{esc(i['count'])}</td></tr>" for i in items)
    body = f\"\"\"<h1>Items</h1>
    <div class="table-wrap"><table class="data"><thead><tr><th>Name</th><th>Count</th></tr></thead>
    <tbody>{rows}</tbody></table></div>\"\"\"
    return 200, page("Equipment loans", body, nav=[("Items", "/"), ("Report", "/report")])
```

`page(title, body, nav=...)` returns the whole document: the header bar, the navigation, the
look chosen at intake, light and dark. Return it as a string and the service sends HTML.

**Always pass every value that came from a person or the data through `esc()`.** That is what
keeps the product safe from script injection.

## Components (classes in product.css)

| Need | Markup |
|---|---|
| A section or panel | `<section class="card"><h2>…</h2>…</section>` |
| A list of records | `<div class="table-wrap"><table class="data">…</table></div>`; numbers go in `<td class="num">` |
| A form | `<form class="form" method="post" action="…">` with `<div class="field"><label for="x">…</label><input id="x" name="x" required><span class="hint">…</span></div>` and `<button class="button">Save</button>` |
| A status | `<span class="badge ok">Returned</span>`, `badge warn` (due soon), `badge crit` (overdue). Always a word, never colour alone |
| Nothing yet | `<div class="empty"><h3>No loans yet</h3><p>Lend the first item to see it here.</p><a class="button" href="/new">Lend an item</a></div>` |
| A message after an action | `<p class="notice">Saved.</p>`, or `notice crit` for an error that says how to fix it |
| Layout | `<div class="stack">` (vertical), `<div class="row">` (wrapping horizontal) |

## Rules

- Use semantic HTML: one `<h1>` per page, labels on every input, real `<button>`s and links.
- Every list has an empty state that says what will appear and how to add the first one.
- Write labels from the user's side ("Lend an item", not "POST loan").
- Errors say what went wrong and how to fix it.
- No inline styles, no other stylesheets, no scripts unless the requirement needs them.
- A JSON API and an HTML page may share a path only if the requirement says so. Otherwise keep
  pages at their own paths, as the spec's interface names them.
"""
