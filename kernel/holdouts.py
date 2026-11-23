"""Holdout steps that sign their requests (FR-DF2).

A webhook a spec requires to be signed answers 401 to an unsigned request, so a holdout scenario
must be able to sign one. A step may carry

    "sign": {"header": "X-Signature", "secret": "WEBHOOK_SECRET", "prefix": "sha256="}

and the runner (`kernel/operate.py` run_scenario) then sends the step's body as exact bytes, with
the HMAC-SHA256 of those bytes, keyed by the secret, as a hex digest (after the optional
``prefix``) in that header.

The scenario names the secret; it never holds it. The name is a setting of the environment: one
of the secrets the environment's paved road names (`secrets` in paved_roads.json: a name, and
where its value lives). The runner reads a value only from a reference it can read,
`env:<VARIABLE>` (the kernel host's environment). Any other reference, an unset variable, or a
name no road gives makes the step **not measured**, never failed. The value is never written to a
scenario, a result, the release record or the ledger: a result names the header and the secret's
name only.

Custody is unchanged: scenarios stay in the holdout custody (`<home>/holdouts/<project>/`), and no
builder sees one; the builder's envelope never names a scenario or what it signs.

A `sign` the runner cannot use is refused before anything is sent (FR-DF2-AC-3): a header that is
not a plain name, or one HTTP itself sends (`Host`, `Content-Length`...), and a prefix that is not
visible ASCII (a line break would start a header of its own). Each scenario runs guarded
(`run_guarded`): one the runner cannot send is not measured, and the others still run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from typing import Any

ALGORITHMS = ("hmac-sha256",)
_SETTING = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")   # an environment setting's name, never a value
_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
# A prefix is visible ASCII (a space inside it allowed): never a line break or a control character,
# which would end the header and start another (FR-DF2-AC-3).
_PREFIX = re.compile(r"^(?:[!-~][ -~]{0,31})?$")
# The headers HTTP itself sends, or the runner sets: a signature in one would replace what frames
# or routes the request, so the scenario would fail for the runner's reason, not the product's.
TRANSPORT_HEADERS = frozenset({
    "host", "content-length", "content-type", "content-encoding", "transfer-encoding", "connection", "keep-alive",
    "upgrade", "te", "trailer", "expect", "proxy-authorization", "proxy-connection", "accept-encoding"})
ENV_REF = "env:"


class NotSigned(ValueError):
    """A step asks to be signed and cannot be: its scenario is not measured, not failed."""


def _header_refused(header: str) -> str | None:
    """Why ``header`` cannot carry a signature, or None when it can."""
    if not _HEADER.fullmatch(header):
        return "not measured: a step's sign names the header the signature goes in (letters, digits and -)"
    if header.lower() in TRANSPORT_HEADERS or header.lower().startswith("proxy-"):
        return (f"not measured: {header} is a header HTTP itself sends; a sign puts the signature in a header "
                "of its own")
    return None


def clean_sign(sign: Any) -> dict[str, str]:
    """A step's `sign` with only the keys the runner reads. One the runner cannot use keeps a
    `refused` reason instead, and a secret that is not a setting's name (it may be a value) is not
    kept at all; nor is a header or a prefix the runner refuses."""
    if not isinstance(sign, dict):
        return {"refused": "not measured: a step's sign is an object with a header and a secret's name"}
    header, secret = str(sign.get("header") or ""), str(sign.get("secret") or "")
    algorithm, prefix = str(sign.get("algorithm") or ALGORITHMS[0]), str(sign.get("prefix") or "")
    refused = _header_refused(header)
    if refused:
        return {"refused": refused}
    if not _SETTING.fullmatch(secret):
        return {"header": header, "refused": "not measured: a sign names its secret by the environment's setting "
                                             "(CAPITALS_AND_UNDERSCORES), never by its value"}
    if algorithm not in ALGORITHMS or not _PREFIX.fullmatch(prefix):
        why = (f"not measured: a step signs with {', '.join(ALGORITHMS)}, and a prefix of at most 32 visible "
               "characters (no line break)")
        return {"header": header, "secret": secret, "refused": why}
    return {"header": header, "secret": secret, "algorithm": algorithm, **({"prefix": prefix} if prefix else {})}


def clean_step(step: dict[str, Any]) -> dict[str, Any]:
    """A step as the holdout author wrote it, its `sign` (if any) cleaned before it enters custody."""
    return step | {"sign": clean_sign(step["sign"])} if "sign" in step else step


def body_bytes(body: Any) -> tuple[bytes | None, dict[str, str]]:
    """The exact bytes a step's body is sent as, and the content type they imply."""
    if body is None:
        return None, {}
    if isinstance(body, str):
        return body.encode("utf-8"), {"Content-Type": "text/plain; charset=utf-8"}
    return json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"}


def prepare(step: dict[str, Any], secrets: dict[str, str | None] | None) -> tuple[Any, dict[str, str], dict | None]:
    """What to send for one step: the body, the extra headers, and what was signed (names only).
    An unsigned step is sent as before. Raises NotSigned when the step cannot be signed."""
    if "sign" not in step:
        return step.get("body"), {}, None
    sign = clean_sign(step["sign"])
    if "refused" in sign:
        raise NotSigned(sign["refused"])
    name = sign["secret"]
    if name not in (secrets or {}):
        raise NotSigned(f"not measured: the environment's settings name no secret {name}")
    value = (secrets or {})[name]
    if not value:
        raise NotSigned(f"not measured: the secret {name} lives where the holdout runner cannot read it "
                        f"(it reads `{ENV_REF}<VARIABLE>` references that are set)")
    raw, headers = body_bytes(step.get("body"))
    digest = hmac.new(value.encode("utf-8"), raw or b"", hashlib.sha256).hexdigest()
    headers[sign["header"]] = sign.get("prefix", "") + digest
    return raw, headers, {"header": sign["header"], "secret": name}


def run_guarded(run: Any, base_url: str, scenario: dict, **kwargs: Any) -> dict:
    """One scenario, run so that it cannot stop the others (FR-DF2-AC-3). A scenario the runner
    cannot send (a step http.client refuses, a step that is not an object) is not measured; its
    reason names the error's kind only, never its text, which may quote what the step sent."""
    try:
        return run(base_url, scenario, **kwargs)
    except Exception as exc:  # one scenario the runner cannot send is that scenario's, never the release's
        return {"criterion": scenario.get("criterion"), "kind": scenario.get("kind", "holdout"),
                "steps": len(scenario.get("steps") or []), "trail": [], "verdict": "not measured",
                "reason": f"not measured: the holdout runner could not send this scenario ({type(exc).__name__})"}


def environment_secrets(road: Any) -> dict[str, str | None]:
    """The secrets a road names for its environments, by name: each value read from its `env:`
    reference, or None where the runner cannot read it. Kept in memory, never written."""
    refs, _problems = road.secrets()
    out: dict[str, str | None] = {}
    for s in refs:
        ref = str(s.get("ref") or "")
        out[s["name"]] = os.environ.get(ref[len(ENV_REF):]) or None if ref.startswith(ENV_REF) else None
    return out


def secret_names(project: Any) -> list[str]:
    """The names of the secrets the roads of the project's delivery plan give, for the holdout
    author's prompt: names only, never a value or where it lives."""
    from kernel.deliver import delivery_plan, plan_environments
    from kernel.roads import PavedRoads

    paved = PavedRoads.load(project.factory)
    names: set[str] = set()
    for env in plan_environments(delivery_plan(project.meta["maturity"])):
        road = paved.name_for(project, env)
        cfg: dict[str, Any] = (paved.roads.get(road) or {}) if road else {}
        names |= {str(s["name"]) for s in cfg.get("secrets") or [] if isinstance(s, dict) and s.get("name")}
    return sorted(n for n in names if _SETTING.fullmatch(n))


def signing_rules(names: list[str]) -> str:
    """How a holdout author signs a request, for the interface section of its prompt (FR-DF2-AC-2)."""
    known = (f"The environment's settings name these secrets: {', '.join(names)}." if names else
             "The environment's settings name no secret yet: use the setting name the spec gives, and IT names it "
             "on the road.")
    return ("Signed requests: when the spec says a request must be signed (an HMAC signature in a header), give that\n"
            'step "sign": {"header": "<the header the spec names>", "secret": "<the secret\'s setting name>"}.\n'
            "The runner sends the body as exact JSON bytes and puts the hex HMAC-SHA256 of those bytes, keyed by\n"
            "that secret, in the header (\"prefix\": \"sha256=\" puts text before the digest). The header is one\n"
            "of the product's own (never Host, Content-Length or Content-Type). Never write a\n"
            "secret's value in a scenario: name it. " + known)
