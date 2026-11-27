"""A failing infrastructure check opens an incident with its evidence and the remedy where one is known (FR-ITO1,
with FR-HEAL1).

``on_result`` is called by kernel/checks/store.py after each recorded run. When an infrastructure check (app, tls,
dns, database, integration, job, ml, agent) turns failed (once per change to failed, never once per run), it:

- opens an incident (kernel/incidents.py, kind ``check_failed``, where ``check:<key>``) at once, with the check's
  evidence lines as its log, its summary, and the remedy for what failed. The ledger sweep's own incident for the
  same ``check_ran`` record has the same fingerprint, so it is counted on this one, never opened twice;
- records ``infra_check_failed`` in the project's ledger (``source`` is the check's kind, ``ref`` its key), so an
  automation can react to one kind failing ("alert on a failing integration", kernel/itops_suggest.py).

``classes()`` are the incident classes kernel/immune.py puts first: each infrastructure kind's explanation and
remedies (a link to where it is fixed, or the steps), so Investigate and Remedies say what to do.
"""

from __future__ import annotations

from typing import Any

INFRA = ("app", "tls", "dns", "database", "integration", "job", "ml", "agent")

REMEDY: dict[str, str] = {
    "app": "Open where it runs (Destinations) and check the release: restart it on its road, or roll back to the "
           "last release whose health endpoint answered; a slow answer: look at what changed in the last release",
    "renew": "Renew the certificate before it expires (your certificate authority, or the platform's automatic "
             "renewal), deploy it where the service runs, then run the TLS check again",
    "tls": "Read the certificate's problem in the evidence: install one a browser trusts (from a public certificate "
           "authority, or add the private CA where it must be trusted) and for the name it is asked for, deploy it "
           "where the service runs, then run the TLS check again",
    "network": "Check the name in DNS and the firewall or security group in front of the port; then run the check "
               "again",
    "dns": "Check the name in DNS and the firewall or security group in front of the port; then run the check again",
    "database": "Check that the database server runs and accepts connections from where Rihmasto runs; then run the "
                "check again",
    "backup": "The backup job did not write a new file in time: open the job that makes it, run it, and check where "
              "it writes",
    "integration": "Open Integrations and data: check the system's status page, rotate a credential that expired, or "
                   "ask the provider for more quota",
    "job": "Open the automation that runs it: read its last runs, run it once by hand, and fix what failed",
    "ml": "Open the eval set's latest run on Health: compare its findings with the run before and retrain or roll "
          "back the model",
    "agent": "Open Agent operations: the Optimise audit names the tools that fail and the runs that cost most",
}
LINKS: dict[str, tuple[str, str]] = {
    "app": ("Open Destinations", "#/p/{pid}/destinations"), "tls": ("Open the IT checks", "#/p/{pid}/itops"),
    "dns": ("Open the IT checks", "#/p/{pid}/itops"), "database": ("Open Integrations and data", "#/p/{pid}/itdata"),
    "integration": ("Open Integrations and data", "#/p/{pid}/itdata"), "job": ("Open Automations",
                                                                              "#/p/{pid}/automations"),
    "ml": ("Open Health", "#/p/{pid}/checks"), "agent": ("Open Agent operations", "#/p/{pid}/agentops"),
}
TITLES = {"app": "A health endpoint failed its check", "tls": "A certificate expired, expires soon or is not trusted",
          "dns": "A host does not resolve or answer", "database": "A database check failed",
          "integration": "An integration check failed", "job": "A scheduled job is failing or late",
          "ml": "A model's evals failed or drifted", "agent": "The agents' runs went over their limits"}


def swept(payload: dict[str, Any]) -> bool:
    """Whether the ledger sweep (kernel/heal_wiring.py) opens an incident for a ``check_ran`` record: a failure, or a
    check of another kind that could not measure. An infrastructure check that says "not measured" had nothing to
    measure or a setting to change (the project runs nowhere yet, no database declared): no incident (FR-ITO2)."""
    verdict = payload.get("verdict")
    if verdict == "failed":
        return True
    kind = str(payload.get("kind") or str(payload.get("check") or "").split(":")[0])
    broke = "itself broke" in str(payload.get("summary") or "")         # Rihmasto's own fault: an incident
    return verdict == "not measured" and (kind not in INFRA or broke)


def classes() -> list[dict[str, Any]]:
    from kernel.immune import INVESTIGATE, _a

    out = []
    for kind in INFRA:
        label, href = LINKS[kind]

        def match(doc: dict[str, Any], kind: str = kind) -> bool:
            where = str(doc.get("where") or "")
            return doc.get("kind") == "check_failed" and (where == f"check:{kind}" or where.startswith(
                f"check:{kind}:")) and not str(doc.get("message") or "").startswith("not measured")

        out.append({"id": f"infra_{kind}", "title": TITLES[kind], "classification": "external",
                    "explain": "An infrastructure check failed; its evidence is in the incident.",
                    "match": match,
                    "remedies": [_a(f"infra_{kind}_how", "What to do", "explain", text=REMEDY[kind]),
                                 _a(f"infra_{kind}_open", label, "link", href=href, why=REMEDY[kind][:160]),
                                 INVESTIGATE]})
    return out


def on_result(project: Any, key: str, entry: dict[str, Any], row: dict[str, Any], before: str | None) -> str | None:
    """Open the incident for an infrastructure check that turned failed; its id, or None."""
    kind = str(entry.get("kind") or key.split(":")[0])
    if kind not in INFRA or row.get("verdict") != "failed" or before == "failed" or project.pid.startswith("_"):
        return None
    from kernel import incidents

    remedy = REMEDY.get(str(row.get("remedy") or kind), REMEDY[kind])
    try:
        doc = incidents.open_incident(project.factory, kind="check_failed", where=f"check:{key}",
                                      message=f"failed: {row.get('summary') or ''}", project=project.pid,
                                      by="the infrastructure checks",
                                      context={"trace": list(row.get("evidence") or [])[:20], "remedy": remedy,
                                               "check": key, "persona": (entry.get("by") or {}).get("persona")})
    except (OSError, ValueError, KeyError):
        return None
    project.log("infra_check_failed", {"check": key, "source": kind, "ref": f"check:{key}", "incident": doc["id"],
                                       "verdict": "failed", "summary": str(row.get("summary") or "")[:300]})
    return str(doc["id"])
