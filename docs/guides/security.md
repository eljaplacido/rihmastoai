# Security: Rihmasto checks what it builds

Rihmasto scans and red-teams the products it builds with its own code ([D-0014](../../decisions/D-0014-security-is-native.md)).
It needs no other project and no scanner: the checks are standard-library Python in
`kernel/redteam/`. Every check is proven by a seeded defect it must catch, and by a clean twin it
must stay quiet on. Results are SARIF 2.1.0, judged by the same security gate as any scanner's
([brownfield.md](../brownfield.md#security-findings-from-any-scanner)), and they reach the
release's evidence pack.

There are three layers:

| Layer | What it reads or drives | Needs a scope |
|---|---|---|
| static | a product's source and configuration (Python, JavaScript, HTML and templates, Dockerfiles, GitHub Actions, secrets) | no: nothing runs |
| dynamic | a deployment the factory runs, over HTTP on loopback | yes |
| agentic | the factory's LLM-facing surfaces (the embed chat, the cockpit assistant), with a payload corpus scored by canaries | yes |

Every layer says, per part, `measured`, `partial` or `not measured`, with the reason. Nothing
unmeasured is reported as passed.

## 1. Commands

```bash
# static: no scope, nothing executed
python -m kernel.redteam static path/to/product --sarif scan.sarif --markdown scan.md
python -m kernel.redteam static . --root . --exclude "tests/fixtures/*"
python -m kernel.redteam rules            # the static catalogue; --dynamic for the dynamic one

# dynamic: probes the slot of an environment the factory runs, inside a scope
python -m kernel.redteam dynamic <project id> --env staging --sarif dynamic.sarif --markdown dynamic.md

# agentic: the embed chat or the cockpit assistant, inside a scope
python -m kernel.redteam agentic <project id> --surface embed --sarif embed.sarif --markdown embed.md
python -m kernel.redteam agentic <project id> --surface assistant --model gnomon
python -m kernel.redteam agentic <project id> --surface embed --via http --model none
```

Every command exits `0` passed, `1` failed (findings), `2` a usage or input error, `3` refused by
the scope (nothing was sent), `4` not measured. `--json` prints the whole report. The factory's home
is `RIHMA_HOME` or `--home`.

## 2. Authorise a scope

Dynamic and agentic testing reach only what the factory itself deployed or runs, on loopback, inside
a scope a named person with the `it` or `compliance` persona authorised: the person, the persona,
a reason, the targets and an expiry at most 31 days ahead.

```python
from kernel.store import Factory
from kernel.redteam import scope

project = Factory().project("<project id>")
scope.authorise(project, ["staging", "embed"], "Aino Virtanen", "it", "pre-release test of loans", "2026-11-30")
scope.revoke(project, "RT-SCOPE-001", person="Aino Virtanen", persona="it", reason="release shipped")
```

A scope names environments (`staging` covers its current, candidate and twin slots), one slot
(`staging/twin`), a surface (`embed`, `assistant`), or a loopback URL. Scopes live only in the
project's ledger (`redteam_scope_authorised`, `redteam_scope_revoked`). What `kernel/redteam/scope.py`
enforces:

- **A person.** A name that is one of the factory's own actors, or holds such a word, is refused:
  `Claude Code`, `factory autopilot`, `the model`, `LLM agent`, a single letter. The persona is the
  caller's word (the factory keeps no register of who holds which persona); the report names who
  authorised.
- **At most 31 days, in UTC.** An expiry's time zone cannot stretch it (`23:59:59-12:00` is the
  next day in UTC).
- **Checked again when read.** Every scope record is validated as `authorise` validates it each
  time it is read: a record written straight into the ledger that breaks a rule (no person, a
  persona that may not, no reason, too long, no expiry) is `invalid` and authorises nothing; a
  ledger that does not verify authorises nothing.
- **A URL is bound.** A scope that names a loopback URL is bound, when it is authorised, to the
  environment and slot the factory runs there. If another environment later lands on the same port,
  the scope does not cover it. A URL where nothing the factory deployed runs cannot be authorised.

Before any request is sent, a target must pass three checks, and a refusal is recorded in the
ledger (`redteam_target_refused`, the URL without user information or query):

1. **Loopback**: an IP literal in 127.0.0.0/8 or ::1, over http or https, with no user name or
   password. A host name such as `localhost` is refused: it could resolve elsewhere.
2. **Deployed or run by the factory**: the `base_url` of a slot in
   `envs/<environment>/<slot>.json`, for one of the factory's own environments and slots, labelled by
   its path (a file that claims another place is not taken at its word), whose process, when the
   slot names one, still runs. Or a surface the factory started for this run: its address is read
   from the server object or the process the factory started (`kernel/redteam/started.py`), never
   from what a caller declares.
3. **In an unexpired, valid scope** that names it.

## 3. Static scan

`static` reads every file under the paths given; nothing is executed, imported or downloaded.
Python is read with the standard library's `ast` (honouring a `# coding:` declaration, as Python
does); JavaScript, HTML, Dockerfiles, workflows and secrets with careful text rules.

| Rule | Finds | CWE | OWASP Top 10 2025 | Severity |
|---|---|---|---|---|
| RT-PY-SHELL | a shell command built from data: `os.system`, `shell=` anything but false, `["bash", "-c", cmd]`, `os.exec*` with `sh -c`, `asyncio.create_subprocess_shell` | CWE-78 | A05 Injection | high |
| RT-PY-EVAL | eval or exec on a value that is not a literal | CWE-95 | A05 Injection | high |
| RT-PY-DESER | unsafe deserialisation (pickle and its relatives, marshal, shelve, unsafe YAML, torch.load) | CWE-502 | A08 Integrity Failures | high |
| RT-PY-SQL | SQL built by formatting, at `execute`, Django's `raw`, pandas' `read_sql`, SQLAlchemy's `text()` | CWE-89 | A05 Injection | high |
| RT-PY-PATH | a request-derived path opened without a containment check that guards it | CWE-22 | A01 Broken Access Control | high |
| RT-PY-TIMEOUT | a network call without a timeout (also through a session or pool client) | CWE-1088 | A10 Exceptional Conditions | medium |
| RT-PY-WEAKHASH | MD5 or SHA-1 for a password, token or secret | CWE-328 | A04 Cryptographic Failures | high |
| RT-PY-MKTEMP | `tempfile.mktemp` | CWE-377 | A01 Broken Access Control | medium |
| RT-PY-DEBUG | a debug server or debugger (`debug=True`, Django `DEBUG = True`, `DebuggedApplication`) | CWE-489 | A02 Misconfiguration | high |
| RT-PY-BINDALL | binding every interface outside a container's entry point | CWE-1327 | A02 Misconfiguration | medium |
| RT-PY-TLS | TLS verification turned off (`verify=False` or a false constant, `session.verify = False`, a global unverified context, aiohttp `ssl=False`, an emptied CA bundle) | CWE-295 | A07 Authentication Failures | high |
| RT-JS-DOMXSS | HTML written from a value that is not a literal (`innerHTML` in every assignment form, `insertAdjacentHTML`, `document.write`, jQuery `.html()`, React `__html`, Vue `v-html`, Svelte `{@html}`, inline handlers) | CWE-79 | A05 Injection | high |
| RT-JS-EVAL | `eval`, `window.eval`, `(0, eval)`, `Function`, or a timer given built code | CWE-95 | A05 Injection | high |
| RT-HTML-SRI | a script from another origin without an integrity hash, read as a browser reads the address; a module imported from another origin | CWE-353 | A08 Integrity Failures | medium |
| RT-DOCKER-ROOT | the final stage runs as root (heredocs and the escape directive read as Docker reads them) | CWE-250 | A02 Misconfiguration | medium |
| RT-DOCKER-ADDURL | ADD of a URL without a checksum, or RUN piping a download into a shell | CWE-494 | A08 Integrity Failures | medium |
| RT-DOCKER-UNPINNED | a base image with no tag or `latest` (ARG defaults substituted) | CWE-829 | A03 Supply Chain Failures | medium |
| RT-GHA-INJECT | a `run:` script interpolating event data, directly, through `env.`, through a step output, in a flow mapping or a quoted key | CWE-78 | A05 Injection | high |
| RT-GHA-UNPINNED | an action pinned by a tag or branch, not a commit SHA | CWE-829 | A03 Supply Chain Failures | medium |
| RT-SECRET-FILE | a committed secret file (`.env`, `*.env`, keys, key stores, `.pgpass`, `.aws/credentials`, registry credentials, Terraform state) | CWE-540 | A01 Broken Access Control | high |
| RT-SECRET-PATTERN | a credential with a known format | CWE-798 | A07 Authentication Failures | critical |
| RT-SECRET-ENTROPY | a random-looking value under a credential name (`SECRET_KEY`, `DB_PASS`, `api_token`, `auth`) | CWE-798 | A07 Authentication Failures | high |

Each finding carries its location, a fix and one line of evidence, masked (at most a sixth of a
credential, never more than four characters, stays readable) and trimmed.

**What the walk leaves out, it says.** A symbolic link, a Windows junction, or any file whose real
path is outside the target is not read, and is listed. Version-control and tool caches and
`node_modules` are not read, and each skipped folder is listed with its file count; a folder named
`venv` is skipped only when it is a virtual environment (it holds `pyvenv.cfg`). Paths a person
excludes with `--exclude` are listed. A folder that cannot be listed is a gap. Paths over the
Windows 260-character limit are read. Which layer reads a workflow depends on its real folder, so
scanning a repository, its `.github` folder or one workflow finds the same.

**Canaries.** A secret on a line marked `redteam: canary` (after a comment opener) is a planted
secret only in a test suite (a `tests`, `fixtures` or `spec` folder, or a `test_*` file): it is not
a finding there, it is listed, and it reaches the gate as a SARIF result of kind `review`, level
`note`, suppressed in the source (`RT-CANARY`), so a person can see it is not a real credential. In
the product's own code a marker silences nothing.

**How each rule is proven.** `tests/fixtures/redteam/vulnerable_app` seeds one defect per rule;
`tests/fixtures/redteam/clean_app` is the same product written safely. Independent attackers then
tried to slip defects past the scan: every bypass they reported is a seed in
`tests/fixtures/redteam/bypass_app`, caught at its line with nothing else reported, and the safe
forms and false alarms they found on safe code are in `tests/fixtures/redteam/bypass_clean`, where
nothing may be reported.

## 4. Dynamic probes

`dynamic` probes the slot of the environment the factory runs, on the routes of the project's
fixed interface (`spec.json`). Every request goes through `kernel/redteam/client.py`: the scope is
checked before every single request (a scope revoked or expired mid-run stops the run at its next
request), the run sends at most its budget (`--budget`, 300 by default, 1000 at most), one
connection per request, a timeout, no proxy, no redirect followed. Each run is recorded in the
ledger (`redteam_dynamic_run`).

| Rule | Finds | CWE | Severity |
|---|---|---|---|
| RT-DYN-CSP, -NOSNIFF, -FRAME, -REFERRER | missing security headers (asked as a browser asks, `Accept: text/html`) | CWE-693, CWE-1021, CWE-200 | medium / low |
| RT-DYN-LEAK | an error page with a stack trace, a server path or a database error | CWE-209 | medium |
| RT-DYN-TRAVERSAL | path traversal, plain, encoded, `....//` or by an absolute name | CWE-22 | high |
| RT-DYN-REFLECT | a tag marker sent in a path or query parameter, reflected unescaped into HTML | CWE-79 | high |
| RT-DYN-METHOD | an undeclared write method answered, or TRACE echoing | CWE-650 | medium |
| RT-DYN-MALFORMED | malformed JSON or invalid UTF-8 breaking the server | CWE-755 | medium |
| RT-DYN-OVERSIZE | a server waiting for a 1 GiB body | CWE-770 | medium |
| RT-DYN-CORS | any origin, or `null`, allowed with credentials | CWE-942 | high |
| RT-DYN-RATELIMIT | a write route taking 12 writes in a row without a 429 | CWE-799 | medium |

**The probes never change data.** An undeclared write method goes only to a path with a parameter,
set to `rihmasto-probe`, which names no record; a path without one (`DELETE /items`) would act on
the whole collection, so it is never sent there, and the reason says how many paths that left out.
Bodies are malformed, and the rate-limit probe sends JSON cut short, which no server can store. On
`production` nothing that writes is sent: the bodies and rate-limit layers are not measured, and say
so; probe staging or a twin for them.

**How each probe is proven.** `tests/fixtures/redteam/dynamic/vulnerable/app/server.py` seeds one
defect per rule, and its clean twin must stay quiet with every layer measured.

## 5. Agentic red team

`agentic` attacks the embed chat (`POST /e/<id>/messages`) or the cockpit assistant
(`kernel.assistant.ask`, or `POST /api/assistant`) with the corpus in `kernel/redteam/payloads.json`:
instruction override, system prompt extraction, exfiltration of the project's records, the holdout
custody and another project's data, tool or action abuse, encoding and language tricks, multi-turn
escalation.

| Option | Means |
|---|---|
| `--model worst-case` (default) | a scripted model fully on the attacker's side: a clean run shows the factory's own guards hold even when the model is compromised |
| `--model gnomon` | the real model, as the server runs it; its answers vary, so a clean run is evidence, not proof |
| `--model none` | no model: the surface's fixed answers and filing |
| `--via direct` (default) | the surface's kernel code in process: every prompt the surface built is seen |
| `--via http` | the factory's own server started on the sandbox, on 127.0.0.1; prompts are then not seen, and exposure says not measured |

**Scored by canaries.** Fresh canaries are planted in a sandbox copy of the project (a holdout
scenario, the internal brief, a decision's reason, another project's records; for the chat also an
open card and question). After each attempt the red team searches every reply, proposal, filed card
and every record the attempt changed, and what the surface said over the whole conversation put
together, for every canary in every form `kernel/redteam/canary.py` knows: plain, obfuscated
(spacing, case, full-width, look-alike and small-capital letters, accents, zero-width and invisible
tag characters, digits of any script, interleaving, numbered lines), reversed, Caesar shifts, Atbash,
ROT47, escapes, base64 (also broken up or ending the text), base32, base85, uuencode, hex,
character codes, and in part. It searches the prompts the model was given for canaries the attacker
did not send. Every proposal is judged again from the Inbox's rules (`kernel/redteam/judge.py`), and
the sandbox's files are compared before and after each attempt: the chat may only file change cards
on its own project and append to its ledger; the assistant writes nothing.

**Inside the scope, all the way.** The scope is checked before the run, before every turn and
before every question the surface puts to the run's model: a scope revoked or expired mid-run stops
the run, the refusal is recorded, and what was not tried is not measured. Over HTTP, only a server
the factory started on the sandbox is driven.

| Rule | Finds | CWE |
|---|---|---|
| RT-AI-LEAK | a canary came out in a reply, proposal, filed card, changed record or the conversation | CWE-200 |
| RT-AI-EXPOSED | a canary reached the model's prompt | CWE-201 |
| RT-AI-ACTION | an action the factory's rules do not allow was offered or taken, or a record it may not touch was written | CWE-863 |

**How each check is proven.** `tests/fixtures/redteam/agentic/leaks.json` and `leaks_missed.json`
hold one canary in every form, which must be found, and near misses, which must not;
`tests/fixtures/redteam/agentic/broken_guards.py` seeds defects patched into the kernel for one test
each, which must be caught in their layer, while the kernel as it is must yield nothing.

## 6. From the result to the gate and the evidence pack

```bash
rihma security ingest <project id> scan.sarif --person "<your name>" --persona compliance
rihma security status <project id>
```

Each kind of scan is its own tool in SARIF (`Rihmasto red team (static)`, `(dynamic)`,
`(agentic embed)`, `(agentic assistant)`), so a later run never replaces another's findings. The
security gate (`kernel/security.py`) reads them like any scanner's: by default it blocks on `error`
findings; a person may accept a risk, and the acceptance follows a finding by its fingerprint when
lines move. A coverage gap travels as a result of kind `open` (`RT-COVERAGE`, level `none`); gate on
`none` too if a gap must hold a release. A scan that measured nothing writes no SARIF: an empty log
would read as a pass. The release's evidence pack carries the latest scan per tool, its counts and
the accepted risks (`security.json`).

## 7. Rihmasto scans itself

```bash
python -m kernel.redteam static . --root . --exclude "tests/fixtures/redteam/*"
```

The seeded fixtures are excluded on purpose (they are defects by design), and the exclusion is
listed in the report. What remains: actions pinned by tag in `.github/workflows/ci.yml` and in the
archived `blueprint/` sample run (true per the rule), and two DOM findings in design pages under
`docs/` that build HTML only from the page's own arrays through local variables and helpers, which
the rule cannot follow (false positives, said here rather than hidden by narrowing the rule).

## 8. What it does not catch

Said so a reader can judge each layer, not hidden:

**Static.**
- `RT-PY-PATH` and the shell and SQL rules work inside one function: a value that crosses a call
  (other than a module function returning a SQL string), is stored and read back, or travels
  through an object other than `self`, is not followed. A containment check in a helper function is
  not seen, so such a function is reported.
- A request-like parameter name counts as request data only in a module that imports a web
  framework; a web handler in a module that imports none, with a non-request name, is not a source.
- The JavaScript rules are regular expressions, not a parser: a sink reached through an alias
  (`const w = document.write`), computed property names, nested template literals, and data built
  through local variables or helpers are not followed (data is then reported, not passed).
  Server-side JavaScript (Node: `child_process.exec`, SQL, `res.sendFile`) has no rule.
- Server-side template injection (`{{ x|safe }}`, `| raw`) is not checked.
- In workflows, the `script:` body of `github-script` is not read; a step output is followed only
  when it is set from event data in the same file.
- `RT-DOCKER-UNPINNED` accepts any version tag; only a digest pins an image for good. A slot without
  a process id (the docker road) is taken as running; its container is not inspected.
- A credential split over several string literals (`"ghp_" + "..."`) is not joined.
- SHA-1 required by a protocol (the HaveIBeenPwned range lookup) is reported unless the call says
  `usedforsecurity=False`.

**Dynamic.**
- One request in each place reveals what it reveals: no login, no stored injection, injection into
  GET routes only, traversal in a path parameter only (not in a query such as `?file=`), and only
  toward the files it knows. Missing: open redirects, exposed `/.env` or `/.git/config`, cookie
  flags, missing authorisation on admin pages, a traceback in a 200 answer, boolean SQL injection,
  XSS in a JavaScript string or an attribute where only `<` and `>` are escaped, CORS suffix checks,
  rate limits keyed on `X-Forwarded-For`, and `X-HTTP-Method-Override`. The static layer covers some
  of these in source; the rest need a person or a specialised scanner.
- A rate limit above 12 writes in a row is reported as missing, by design; a limiter that counts
  only stored writes is reported too.
- The header rules check presence, not strength: `script-src 'unsafe-inline'` passes.

**Agentic.**
- A canary spelled out in words, transliterated beyond the look-alikes, encoded twice, revealed
  only in half, or spread over turns with other words between the pieces is not found.
- The judge checks whether a proposal is allowed, not whether the person asked for it: an
  attacker-chosen action the rules allow (an embed for a named https website, a pause by a persona
  that may pause) reaching a privileged person is not reported. Stored injection (a visitor's text
  filed through the chat, then shown to the assistant) and forged prompt delimiters are not in the
  corpus, nor is a `need` embed.
- The corpus is fixed: a clean run shows the guards against these attacks, not every attack.
- Over HTTP the prompts are not seen; `--model gnomon` needs Gnomon on the machine and is not run
  by the tests.

**The scope.** Anyone who can append to the project's ledger can write a correctly chained scope
record that passes every rule (the chain has no key): the ledger's integrity is the boundary. The
persona is the caller's word. An in-process caller with code access can still register a process it
launched itself; the address such a process printed is trusted.
