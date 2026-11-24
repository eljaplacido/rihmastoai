"""`rihmasto contract export`: "spec only" ends in files (FR-MOD3).

A need becomes a confirmed spec and a hashed contract, and nothing is built: the export writes them to a
folder of their own, for whoever builds next (your own team, your own agents, another factory):

- `spec.json` and `spec.md`: the requirements, each with who stands behind it (provenance);
- `contract.json`: compiled with no model, its hash its revision; `checkplan.json`: each criterion's check
  and custody, so a builder knows which tests to name (`test_R_1_AC_1_...`);
- `brief.md`: the brief, each statement tagged owner, assumed or proposed;
- `REPORT.md`: what was decided and by whom: the questions people answered, what was assumed and until
  when, the decisions with their person and persona, and the contract's counts;
- `MANIFEST.json`: the sha256 of every file, and who exported it.

Holdout scenarios are never exported: they stay in their custody, and the check plan names only which
criteria they hold. The export is recorded in the project's ledger with the person, the persona and the
manifest's sha256, and an export never replaces an earlier one's folder.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from kernel.attach import check_signer
from kernel.canon import Canon
from kernel.store import Project, write_text


def _decision_lines(canon: Canon) -> list[str]:
    rows = canon.decisions()
    if not rows:
        return ["- none yet"]
    return [f"- {d.get('card', '-')}: {d.get('verdict', '-')} by {d.get('person', '-')} ({d.get('persona', '-')})"
            + (f": {d['reason']}" if d.get("reason") else "") + (" (stale)" if d.get("stale") else "") for d in rows]


def _question_lines(canon: Canon) -> list[str]:
    out = []
    for q in canon.questions():
        answer = q.get("answer") or {}
        if q["status"] == "answered":
            out.append(f"- {q['id']} {q['text']} Answered by {answer.get('by')}: {answer.get('text')}")
        elif q["status"] == "assumed":
            out.append(f"- {q['id']} {q['text']} Assumed ({answer.get('assumption')}): {answer.get('text')}")
        else:
            out.append(f"- {q['id']} {q['text']} Open" + (" and blocking" if q.get("blocking") else ""))
    return out or ["- none"]


def report(project: Project, contract: dict[str, Any]) -> str:
    """REPORT.md: what the contract rests on, and who decided it."""
    canon = Canon(project)
    lines = [f"# {project.meta.get('title')}: spec and contract", "",
             f"Project `{project.pid}`. Contract revision `{contract['revision']}`: "
             f"{contract['counts']['requirements']} requirements, {contract['counts']['criteria']} criteria, "
             f"{contract['counts']['tasks']} tasks. Nothing was built from it here.", "",
             "## Requirements and who stands behind them", ""]
    for r in contract["requirements"]:
        who = f", decided by {r['decided_by']}" if r.get("decided_by") else ""
        lines.append(f"- **{r['id']}** ({r['provenance']}{who}): {r['statement']}")
        lines += [f"  - {c['id']} [{(c.get('check') or {}).get('kind', 'test')}]: then {c['then']}"
                  for c in r["acceptance"]]
    lines += ["", "## Questions", "", *_question_lines(canon), "", "## Assumptions", ""]
    lines += [f"- {a['id']} ({a['status']}, due {a.get('due')}): {a['text']}"
              for a in canon.assumptions()] or ["- none"]
    lines += ["", "## Decisions", "", *_decision_lines(canon), "",
              "## How to build on it", "",
              "- Name each test after the criterion it shows: `test_R_1_AC_1_...` for R-1-AC-1. A test that passes "
              "before the change shows nothing.",
              "- Holdout criteria are checked against the running service by scenarios kept apart from the builders; "
              "they are not in this folder.",
              "- `rihmasto repo attach` with this contract and `rihmasto repo gate` judge your changes against it.", ""]
    return "\n".join(lines)


def _new_folder(out_dir: Path, stem: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        folder = out_dir / (stem if n == 1 else f"{stem}-{n}")
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            n += 1


def export(project: Project, out_dir: str | Path, *, person: str, persona: str) -> dict[str, Any]:
    """Write the spec, the contract, the check plan, the brief and the report to a new folder."""
    check_signer(person, persona)
    contract = project.read("contract.json")
    if not contract:
        raise FileNotFoundError(f"{project.pid} has no contract yet: `rihmasto run {project.pid}` compiles it "
                                "once the spec is written")
    texts: dict[str, str] = {"contract.json": json.dumps(contract, indent=2, ensure_ascii=False) + "\n",
                             "checkplan.json": json.dumps(project.read("checkplan.json") or {}, indent=2) + "\n",
                             "REPORT.md": report(project, contract)}
    for name, source in (("spec.json", "spec.json"), ("spec.md", "spec.md"), ("brief.md", "canon/brief.md")):
        if project.path(source).exists():
            texts[name] = project.path(source).read_text(encoding="utf-8")
    manifest = {name: hashlib.sha256(t.encode("utf-8")).hexdigest() for name, t in sorted(texts.items())}
    folder = _new_folder(Path(out_dir), f"{project.pid}-contract-{contract['revision'].split(':')[-1][:12]}")
    for name, text in texts.items():
        write_text(folder / name, text)
    write_text(folder / "MANIFEST.json", json.dumps({"files": manifest, "project": project.pid,
                                                      "revision": contract["revision"], "exported_by": person,
                                                      "persona": persona}, indent=2) + "\n")
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    project.log("contract_exported", {"folder": folder.name, "revision": contract["revision"], "person": person,
                                      "persona": persona, "manifest_sha256": digest, "files": sorted(texts)})
    return {"project": project.pid, "folder": str(folder), "revision": contract["revision"], "files": sorted(texts),
            "manifest_sha256": digest, "not_exported": "holdout scenarios: they stay in their custody"}
