# Security

## Supported versions

Rihmasto is in development. Security fixes go to the `main` branch and the latest release.

| Version | Supported |
|---|---|
| 1.0.0.dev0 (latest) | yes |
| anything older | no |

## Report a vulnerability

Report it privately, through GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**. Only the maintainers can read the report.

Please do not post the details in a public issue, a pull request or a discussion.

A good report says what is affected (a file, a route, a command), how to reproduce it, what an
attacker gains, and the version or commit you tested. A maintainer will acknowledge the report,
keep you informed while it is fixed, and credit you in the advisory unless you prefer not.

## Scope

**In scope:** the code in this repository:
- the kernel (`kernel/`), the adapters (`adapters/`) and the tools (`tools/`);
- the cockpit (`cockpit/`), the embed server (`embed/`), the MCP server (`mcp/`) and the
  capability gateway (`gateway/`);
- the Gnomon surface this repository ships (`.gnomon/`), the surfaces the kernel compiles for
  lanes, and the paved-road product template.

Examples: getting past the cockpit's sign-in, Host or Origin checks; a decision recorded for a
persona that may not make it; a builder that can read holdout scenarios; an embed that reads a
project's records; an MCP tool that decides; a ledger change the chain check misses; a secret
written into the repository, a ledger, a pack or a log; a path that escapes the factory home.

**Out of scope:**
- vulnerabilities in Gnomon itself: report them to
  [Gnomon's repository](https://github.com/eljaplacido/gnomonharness);
- model providers, model endpoints and what a model writes (judging a model's work is the gate's
  job; a way around the gate is in scope);
- the limits this page and the docs already state, such as the cockpit having no user accounts;
- products that people build with Rihmasto, except where the paved-road template itself is the
  cause;
- attacks that need control of the machine that runs the factory.

## The threat model in short

Rihmasto runs model-written code and takes input from people who are not its operators. Its
defences rest on a few rules: models never decide, builders never see their own exam, every
surface that faces a network does one thing, and secrets never enter the repository.

### The cockpit

The cockpit is the operator's web page and the Inbox's write path ([docs/cockpit.md](docs/cockpit.md)).

- **Loopback only.** It binds to 127.0.0.1 and refuses any other address. From another machine,
  reach it through an SSH tunnel.
- **A one-use sign-in.** The server prints a link with a one-use code. The page exchanges it once
  for a session token; the link does not work a second time.
- **A bearer token.** Every API request needs `Authorization: Bearer <token>`. There are no
  cookies and no CORS headers.
- **Host and Origin checks.** A request is answered only when its `Host` is the server's own, and
  a POST only when its `Origin` is.
- **A Content-Security-Policy** that allows only the page's own scripts and stylesheets, with no
  inline script or style. The static files hold no data.
- **The kernel decides.** A decision with the wrong persona, a verdict the card does not take, or
  a name that is not a person is refused, and nothing is recorded. Every write is noted in the
  ledger.

Limit: the cockpit has no user accounts. Whoever holds the session can pick any persona. Treat it
as a single-operator tool.

### Embeds

A website chat reaches the factory through the embed server, which is separate from the cockpit
([docs/guides/embeds.md](docs/guides/embeds.md)).

- **Allowed origins.** A message is accepted only from the websites the embed lists. CORS answers
  those origins only.
- **A hashed key.** The key is shown once, and only its sha256 hash is stored. It is publishable,
  like a site key; the origins, the rate limit and the single capability are what protect it.
- **A rate limit** per embed, and caps on message length, body size and turns.
- **One capability.** An embed files feedback as a change card on its own project, or a need as a
  signal. It never reads the canon, decides anything, or sees another project.
- **Loopback by default.** It serves websites only behind IT's TLS reverse proxy.

### The MCP server

The MCP server gives a developer's own coding agent the cockpit's reads ([docs/mcp.md](docs/mcp.md)).

- **Reads and proposals only.** It has no tool that decides, answers, approves, pauses, advances
  or deploys. A test checks the tool list.
- **One signer,** set when it starts. It refuses to start for a name that is not a person.
- **Nothing outside the factory home.** Paved roads, credentials and environment variables are
  never served. It speaks over stdio only.

### Holdouts in custody

Holdout scenarios are the checks a builder must not see. They live in `<home>/holdouts/<id>/`,
outside the project folder, the product repository and every lane. They never enter a builder's
envelope. Packs carry their scores, never their content. The MCP server never serves them, and
redacts any quotation of them in the kernel's own records.

### Builder cells

Every model call goes through Gnomon. A product lane's surface confines the builder to its
envelope's write scope, in a sandbox with no network, and denies destructive git commands. The
kernel runs the checks itself, apart from the builder. The contract and specs are write-protected
for every role of the factory's own surface. Trusting a surface that grants more than Gnomon's
defaults is the owner's act, never an agent's.

### Secrets

- Secrets never go in the repository. `.gitignore` excludes `.env` files.
- A model endpoint names the environment variable that holds its key (`api_key_env`).
  `rihmasto doctor` says whether it is set, never its value.
- A deploy package carries secret references (a name and where the value lives), never values. A
  value found in a road is dropped, and the package fails validation.

### The ledger

Every transition is appended to a hash-chained ledger, so a rewritten or removed record breaks
the chain. The cockpit remembers the last head it verified and reports a ledger that was cut
after it. Signed and externally anchored ledger heads are not built yet.

### Integrations

Connections to outside systems are designed to run through Gnomon as governed tool calls, with
inbound content treated as data, never as instructions
([docs/integrations.md](docs/integrations.md#3-architecture)). They are not built yet.
