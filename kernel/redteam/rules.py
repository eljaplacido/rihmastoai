"""The rule catalogues: what each rule finds, how bad it is, and how to fix it.

Every rule names one CWE weakness and one category of the OWASP Top 10 2025. Every rule of the
static layer (`RULES`) is proven by a seeded defect in `tests/fixtures/redteam/vulnerable_app` (a
line marked `seeded: <rule id>`) and kept honest by `tests/fixtures/redteam/clean_app`, the same
product written safely, where it must find nothing. Every rule of the dynamic layer
(`DYNAMIC_RULES`, probes of a running deployment) is proven the same way by the seeded server in
`tests/fixtures/redteam/dynamic/vulnerable` and its clean twin in `.../dynamic/clean`.

Severity and SARIF level go together: critical and high are `error` (the security gate blocks on
them by default), medium is `warning`, low is `note`.

The OWASP category of a rule is the one OWASP's own list maps its CWE to where it does (CWE-295
to Authentication Failures, CWE-540 to Broken Access Control); otherwise the closest category by
what the defect lets an attacker do.
"""

from __future__ import annotations

from dataclasses import dataclass

OWASP_2025 = {
    "A01:2025": "Broken Access Control",
    "A02:2025": "Security Misconfiguration",
    "A03:2025": "Software Supply Chain Failures",
    "A04:2025": "Cryptographic Failures",
    "A05:2025": "Injection",
    "A06:2025": "Insecure Design",
    "A07:2025": "Authentication Failures",
    "A08:2025": "Software or Data Integrity Failures",
    "A09:2025": "Security Logging and Alerting Failures",
    "A10:2025": "Mishandling of Exceptional Conditions",
}
SEVERITY_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}
# GitHub code scanning reads `security-severity` (0.0 to 10.0) from a rule's properties.
SEVERITY_SCORE = {"critical": "9.5", "high": "8.0", "medium": "5.5", "low": "3.0"}

# The layers of the static scan, in the order a report lists them.
LAYERS = ("python", "javascript", "html", "dockerfile", "actions", "secrets")


@dataclass(frozen=True)
class Rule:
    """One check: its id, what it finds, where (the layer), how bad, and what to do instead."""

    id: str
    title: str
    layer: str
    severity: str
    cwe: str
    owasp: str
    fix: str

    @property
    def level(self) -> str:
        return SEVERITY_LEVEL[self.severity]


def _rule(rid: str, title: str, layer: str, severity: str, cwe: str, owasp: str, fix: str) -> Rule:
    return Rule(rid, title, layer, severity, cwe, owasp, fix)


_CATALOGUE = (
    _rule("RT-PY-SHELL", "Shell command built from data", "python", "high", "CWE-78", "A05:2025",
          "Pass a list of arguments without shell=True (subprocess.run([...])); never build a shell string from data."),
    _rule("RT-PY-EVAL", "eval or exec on a value that is not a literal", "python", "high", "CWE-95", "A05:2025",
          "Parse data with json.loads or ast.literal_eval; dispatch on a fixed table instead of evaluating code."),
    _rule("RT-PY-DESER", "Unsafe deserialisation", "python", "high", "CWE-502", "A08:2025",
          "Read data with json, or yaml.safe_load; never unpickle or marshal what crossed a trust boundary."),
    _rule("RT-PY-SQL", "SQL built by string formatting", "python", "high", "CWE-89", "A05:2025",
          "Use placeholders and pass the values separately: execute(\"... WHERE x = ?\", (value,))."),
    _rule("RT-PY-PATH", "Request-derived path opened without a containment check", "python", "high", "CWE-22",
          "A01:2025",
          "Resolve the path and check it stays inside its base (Path.resolve().is_relative_to(base)), or reduce "
          "the name with os.path.basename, or match it against an allowlist."),
    _rule("RT-PY-TIMEOUT", "Network call without a timeout", "python", "medium", "CWE-1088", "A10:2025",
          "Pass timeout= to every network call, so a slow peer cannot hold a worker forever."),
    _rule("RT-PY-WEAKHASH", "Weak hash (MD5 or SHA-1) for a password, token or secret", "python", "high", "CWE-328",
          "A04:2025",
          "Hash passwords with a slow, salted function (hashlib.scrypt or pbkdf2_hmac); compare tokens with "
          "hmac.compare_digest over SHA-256 or better."),
    _rule("RT-PY-MKTEMP", "tempfile.mktemp: a predictable temporary name", "python", "medium", "CWE-377", "A01:2025",
          "Use tempfile.mkstemp, NamedTemporaryFile or TemporaryDirectory, which create the file safely."),
    _rule("RT-PY-DEBUG", "Debug server or debugger enabled", "python", "high", "CWE-489", "A02:2025",
          "Never ship debug=True or the interactive debugger; read the setting from the environment, off by default."),
    _rule("RT-PY-BINDALL", "Binds all network interfaces outside a container entry point", "python", "medium",
          "CWE-1327", "A02:2025",
          "Bind 127.0.0.1 by default; bind all interfaces only in the container's entry point, behind the "
          "platform's network rules."),
    _rule("RT-PY-TLS", "TLS certificate verification turned off", "python", "high", "CWE-295", "A07:2025",
          "Keep verification on (the default context); trust a private CA by passing its bundle, not by "
          "disabling checks."),
    _rule("RT-JS-DOMXSS", "HTML written into the page from a value that is not a literal", "javascript", "high",
          "CWE-79", "A05:2025",
          "Set textContent, or build elements with createElement; if HTML is needed, sanitise it first."),
    _rule("RT-JS-EVAL", "eval or new Function on a value that is not a literal", "javascript", "high", "CWE-95",
          "A05:2025", "Parse data with JSON.parse; never turn text into code."),
    _rule("RT-HTML-SRI", "Script from another origin without an integrity hash", "html", "medium", "CWE-353",
          "A08:2025",
          "Serve the script yourself, or add integrity=\"sha384-...\" and crossorigin=\"anonymous\"."),
    _rule("RT-DOCKER-ROOT", "Container runs as root", "dockerfile", "medium", "CWE-250", "A02:2025",
          "Create a user and switch to it in the final stage (RUN useradd ... then USER app)."),
    _rule("RT-DOCKER-ADDURL", "ADD fetches a URL with no checksum", "dockerfile", "medium", "CWE-494", "A08:2025",
          "Download in a RUN step and verify a pinned checksum, or use ADD --checksum=sha256:..."),
    _rule("RT-DOCKER-UNPINNED", "Base image not pinned", "dockerfile", "medium", "CWE-829", "A03:2025",
          "Pin the base image to a version tag and, for releases, a digest (image:tag@sha256:...)."),
    _rule("RT-GHA-INJECT", "Workflow run step interpolates event data into a shell", "actions", "high", "CWE-78",
          "A05:2025",
          "Pass the value through env: (TITLE: ${{ github.event.issue.title }}) and use \"$TITLE\" in the script."),
    _rule("RT-GHA-UNPINNED", "Action pinned by a mutable tag or branch", "actions", "medium", "CWE-829", "A03:2025",
          "Pin every action and reusable workflow to a full 40-character commit SHA, with the tag in a comment."),
    _rule("RT-SECRET-FILE", "Secret file committed", "secrets", "high", "CWE-540", "A01:2025",
          "Remove the file from the repository and its history, rotate what it held, and keep an example file "
          "instead."),
    _rule("RT-SECRET-PATTERN", "Credential with a known format in the source", "secrets", "critical", "CWE-798",
          "A07:2025",
          "Revoke and rotate the credential now; read it from the environment or a secret store at run time."),
    _rule("RT-SECRET-ENTROPY", "High-entropy value assigned to a credential name", "secrets", "high", "CWE-798",
          "A07:2025",
          "Rotate the value if it is real, and read it from the environment or a secret store at run time."),
)

RULES: dict[str, Rule] = {r.id: r for r in _CATALOGUE}

# The layers of the dynamic scan (kernel/redteam/dynamic.py), in the order a report lists them.
DYNAMIC_LAYERS = ("headers", "errors", "traversal", "injection", "methods", "bodies", "cors", "ratelimit")

_DYNAMIC = (
    _rule("RT-DYN-CSP", "HTML page served without a Content-Security-Policy", "headers", "medium", "CWE-693",
          "A02:2025",
          "Send a Content-Security-Policy with every page (default-src 'self'), so an injected script cannot run."),
    _rule("RT-DYN-NOSNIFF", "Response without X-Content-Type-Options: nosniff", "headers", "low", "CWE-693",
          "A02:2025", "Send X-Content-Type-Options: nosniff with every response, so no browser guesses a type."),
    _rule("RT-DYN-FRAME", "HTML page any site may frame", "headers", "medium", "CWE-1021", "A02:2025",
          "Send Content-Security-Policy: frame-ancestors 'none' (or 'self'), and X-Frame-Options: DENY for "
          "older browsers."),
    _rule("RT-DYN-REFERRER", "HTML page without a safe Referrer-Policy", "headers", "low", "CWE-200", "A01:2025",
          "Send Referrer-Policy: no-referrer (or strict-origin-when-cross-origin), so a URL never leaks to "
          "another site."),
    _rule("RT-DYN-LEAK", "Error page leaks a stack trace, a file path or a database error", "errors", "medium",
          "CWE-209", "A10:2025",
          "Answer errors with a short message (and an id to look up); log the details on the server only."),
    _rule("RT-DYN-TRAVERSAL", "Path traversal reads a file outside the served folder", "traversal", "high",
          "CWE-22", "A01:2025",
          "Decode the name once, reduce it to its last part (os.path.basename) or resolve it and check it stays "
          "inside the folder."),
    _rule("RT-DYN-REFLECT", "Request data reflected unescaped into an HTML page", "injection", "high", "CWE-79",
          "A05:2025",
          "Escape every value written into HTML (html.escape, the product's esc()), and send a "
          "Content-Security-Policy."),
    _rule("RT-DYN-METHOD", "Route answers a method its interface does not declare", "methods", "medium",
          "CWE-650", "A01:2025",
          "Route on method and path together: answer 405 with an Allow header for any other method, and turn "
          "TRACE off."),
    _rule("RT-DYN-MALFORMED", "Malformed request body breaks the server (5xx or no answer)", "bodies", "medium",
          "CWE-755", "A10:2025",
          "Parse the body inside a try, and answer 400 with a short reason to anything that is not what the "
          "route expects."),
    _rule("RT-DYN-OVERSIZE", "Server waits for a request body of any declared size", "bodies", "medium",
          "CWE-770", "A06:2025",
          "Check Content-Length before reading, and answer 413 above what the route needs (64 KB for a form)."),
    _rule("RT-DYN-CORS", "CORS lets any origin read responses", "cors", "high", "CWE-942", "A02:2025",
          "Allow a fixed list of origins only: never echo the Origin header or null, and never send credentials "
          "with a wildcard."),
    _rule("RT-DYN-RATELIMIT", "Write route without a rate limit", "ratelimit", "medium", "CWE-799", "A06:2025",
          "Limit writes per client and route (a token bucket), answering 429 with Retry-After at the limit."),
)

DYNAMIC_RULES: dict[str, Rule] = {r.id: r for r in _DYNAMIC}

# Every rule a report may name, whatever kind of scan found it.
KNOWN: dict[str, Rule] = RULES | DYNAMIC_RULES

_KINDS = {"static": _CATALOGUE, "dynamic": _DYNAMIC}


def rule(rule_id: str) -> Rule:
    """The rule with this id; a KeyError names an id no catalogue holds."""
    return KNOWN[rule_id]


def rules_for(layer: str) -> list[Rule]:
    return [r for r in KNOWN.values() if r.layer == layer]


def catalogue(kind: str = "static") -> list[dict[str, str]]:
    """One catalogue (``static`` or ``dynamic``) as plain rows, for a report or a command line."""
    return [{"id": r.id, "title": r.title, "layer": r.layer, "severity": r.severity, "level": r.level,
             "cwe": r.cwe, "owasp": f"{r.owasp} {OWASP_2025[r.owasp]}"} for r in _KINDS[kind]]
