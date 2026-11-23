# Access: who may decide, and as which persona

Every decision in Rihmasto names a person and a persona. This guide explains how Rihmasto knows that
the person is who they say, and which personas they may act as. The decision behind it is
[D-0016](../../decisions/D-0016-access-through-the-organisations-identity.md); the code is
`kernel/access.py`.

Rihmasto never stores passwords. People sign in through the organisation's own identity provider
(OIDC), at an identity-aware proxy that IT runs in front of the cockpit. Who may act as which persona
is a small file that IT owns.

## The two modes

| | single operator | enforced |
|---|---|---|
| When | no access file (the default) | `projects/_factory/access/access.json` with `"mode": "enforced"` |
| Who signs | whoever holds the cockpit session or the command line types a name | the identity the organisation's sign-in verified, or the local user on the operator's machine |
| Personas | any persona can be picked | only the personas the access file grants on that project |
| The cockpit says | "single operator: personas are self-declared" | "enforced: signed in as <name>" |

**Single operator** is how Rihmasto has always worked, and nothing about it changes. It suits one
person on their own machine, or a demo. The cockpit's header, the person menu and `rihmasto status`
say plainly that personas are self-declared.

**Enforced** is for a team. Each decision is signed by a verified identity, as a persona that a
binding in the access file grants on that project. The card-kind rules still apply on top: a person
granted `it` on a project still decides only the cards an `it` persona may decide.

## How a person's personas are resolved

1. **Who is it?** In the cockpit, the identity is `<issuer>#<user>`: the issuer from the access file
   and the user that IT's proxy puts in its user header. On the operator's own machine, the command
   line and the MCP server use `local:<os user>`, the operating system account that runs them. It is
   read from the operating system, never from an environment variable such as `USERNAME`, which
   anyone can set.
2. **What is their name?** The name in the access file's `people` list. For someone the file does not
   list, the cockpit uses the email the proxy sends. This is the name every record carries; a typed
   name that differs is refused.
3. **Which personas?** Every binding that names the identity as its `subject`, or names one of the
   groups the proxy sends, grants its persona on its scope. A scope is `"*"` (every project, including
   the factory's own records, `_factory`) or a list of project ids. The groups arrive in one header,
   their values joined with commas, so a group binding is only as safe as the group values the identity
   provider sends: see [Groups](#groups).
4. **Where?** A write on a project needs the persona granted on that project. The factory's own
   writes (signals, concepts, embeds, new projects, the factory's autonomy cap) need it on `_factory`.
   A layout or a question to the assistant, which belong to no project, needs the persona granted
   anywhere.

Someone the proxy lets through but the file grants nothing is refused at sign-in. The refusal names
their identity, so IT can copy it into the file.

## The access file

It lives in a folder of its own in the factory home: `projects/_factory/access/access.json`. Rihmasto
only reads that folder; it never writes in it, not even a lock file. So give write permission on that
folder to IT alone, and read permission to the accounts that run the cockpit, the command line and the
MCP server. The folder above it, `projects/_factory`, must stay writable by those accounts: the factory
ledger, the signals, the factory's canon and their lock files live there, and every signed write uses
them.

On Linux or macOS, with an IT account `itadmin` and the operators' group `rihmasto`:

```sh
install -d -o itadmin -g rihmasto -m 0755 <home>/projects/_factory/access
install -o itadmin -g rihmasto -m 0644 access.json <home>/projects/_factory/access/access.json
```

On Windows, as an administrator, with `<operators>` the group whose accounts run Rihmasto (the folder
stops inheriting its parent's permissions; administrators keep full control, the operators read). Create
the folder as IT, so that IT owns it: the owner of a folder can change its permissions.

```bat
icacls "<home>\projects\_factory\access" /inheritance:r /grant:r "Administrators:(OI)(CI)F" "<operators>:(OI)(CI)RX"
```

Anyone who can write `projects/_factory` can still move the whole `access` folder aside (on Linux,
renaming a folder within the same parent needs write permission on the parent only). That does not open
the factory: Rihmasto then refuses every decision, because the factory ledger says access was enforced
(see [Changing it](#changing-it)).

The file itself:

```json
{
  "schema": "rihmasto.access/1",
  "mode": "enforced",
  "changed_by": "local:it-admin",
  "proxy": {
    "issuer": "https://login.example.org",
    "origin": "https://rihmasto.example.org",
    "user_header": "X-Forwarded-User",
    "email_header": "X-Forwarded-Email",
    "groups_header": "X-Forwarded-Groups",
    "secret_header": "X-Rihmasto-Proxy-Secret",
    "secret_env": "RIHMASTO_PROXY_SECRET"
  },
  "people": [
    {"identity": "https://login.example.org#7d1c0f3a", "name": "Aino Example"},
    {"identity": "local:aino", "name": "Aino Example"},
    {"identity": "local:it-admin", "name": "Ilkka Example"}
  ],
  "bindings": [
    {"subject": "https://login.example.org#7d1c0f3a", "persona": "business_owner", "scope": "*"},
    {"subject": "local:aino", "persona": "product_owner", "scope": ["parking-permits-3f2a1b"]},
    {"subject": "local:it-admin", "persona": "it", "scope": "*"},
    {"group": "rihmasto-operations", "persona": "operations", "scope": "*", "note": "the on-call team"}
  ]
}
```

| Field | What it holds |
|---|---|
| `schema` | always `rihmasto.access/1` |
| `mode` | `enforced`, or `single_operator` (then only `changed_by` and `note` may follow) |
| `changed_by` | who IT says changed the file last. In enforced mode, an identity in `people` that a subject binding grants `it` on `"*"`; in single-operator mode, a person's name. It is the file's own claim: the ledger records it as `claimed_by`, beside the file's owner |
| `proxy.issuer` | the identity provider's issuer, `https://` with no query or fragment; it starts every proxied identity |
| `proxy.origin` | the address people open, such as `https://rihmasto.example.org`, with no path. The cockpit accepts this `Host` and `Origin` beside its own |
| `proxy.user_header` | the header that carries the user, set by the proxy |
| `proxy.email_header`, `proxy.groups_header` | optional: the email (used as the name of someone not in `people`) and the groups. The groups header is one value, split at commas ([Groups](#groups)) |
| `proxy.secret_header` | the header that carries the proxy's shared secret |
| `proxy.secret_env` | the name of the environment variable that holds that secret on the cockpit's machine (never the secret itself) |
| `people` | `identity` and `name`: who is who. An identity is `local:<os user>` or `<issuer>#<subject>` |
| `bindings` | a `subject` (a listed identity) or a `group`, a `persona` and a `scope` (`"*"` or a list of project ids); `note` is optional |

The file is checked whole and strictly: an unknown key, a header the cockpit reads for itself (such as
`Authorization` or `Host`), one header named twice, an unknown persona, an empty scope, a binding to an
identity not in `people`, or a `changed_by` who is not IT on every project makes the file invalid.

A request that carries the user, email, secret or groups header more than once is refused. The proxy
sets each of them once; a proxy that appended its value to a copy the client sent, instead of
replacing it, would otherwise let the client choose who it is or add groups.

### Groups

oauth2-proxy joins a claim's values with commas into one header (`flattenHeaders` in
[`pkg/middleware/headers.go`](https://github.com/oauth2-proxy/oauth2-proxy/blob/master/pkg/middleware/headers.go)
runs on the request it forwards), so the cockpit splits the groups header at commas. A comma inside a
group's name cannot be told from the separator: if users can create groups and the provider sends group
names, a group named `x,rihmasto-ops` arrives as the two groups `x` and `rihmasto-ops`. **Bind groups by
an id that no user can choose**, never by a name. With Microsoft Entra ID the groups claim carries the
groups' object ids (GUIDs) unless the app registration is set to send names instead; keep the ids. Where
the provider can only send names, bind only groups that administrators alone create and name, without a
comma, or bind people by subject.

### Changing it

- **Every change is on record.** The first time a write loads a changed file, Rihmasto appends an
  `access_changed` record to the factory ledger (`projects/_factory/ledger.jsonl`). The cockpit also
  records it when it starts. The record holds:
  - `sha256` and `previous`: the file's sha256 and the one before it; `mode`, `valid` and `error`;
  - `claimed_by`: the file's `changed_by`. It is what the file says, not something Rihmasto checked;
  - `file_owner` and `file_modified`: the account that owns the file and when it was last written, as
    the file system records them. Writing into an existing file keeps its owner and replacing the file
    makes the writer its owner, so the owner tells as much as the folder's permissions allow;
  - `detected_by` and `detected_as`: the surface that noticed the change (the cockpit, the command line,
    the MCP server) and who it was serving: the verified identity of the cockpit's request, else the
    operating system's user (`local:<os user>`).
- **It fails closed.** A file that cannot be read or checked refuses every decision, and the cockpit
  refuses every request, whatever mode the file names, with a message saying what is wrong. Fix the
  file and the next request works.
- **Removing it does not switch enforcement off.** Once access was enforced, a missing file refuses
  every decision. Rihmasto knows access was enforced from the factory ledger's last `access_changed`
  record; from the `access` folder, when it is there without its file; and, when both are gone, from any
  project ledger that holds a write signed by a verified identity. The refusal is then recorded again,
  in a factory ledger started anew if the old one was moved away. To go back to a single operator, IT
  writes a file with `"mode": "single_operator"`, and that change is on record too.

## What is checked where

| Surface | In enforced mode |
|---|---|
| The cockpit | Identity only from the proxy's headers, and only on a request that carries the proxy's shared secret, compared in constant time. `/auth` opens a session for that identity and the session answers that identity only; the printed sign-in link is not needed. Every write route that takes a person or persona signs as the verified person and needs the persona granted on its project. The name field is read-only and the persona menu offers only the personas granted on the open project |
| The command line | Signed commands (`decide`, `answer`, `assume`, `change`, `new`, `intake`, `adopt`, `workspace`, `security`, `evidence`, `embed`, `autonomy set`, `signal log`, `concept edit`) run as `local:<os user>`, which must be in the file. `--person` (for `new` and `intake`, `--requested-by`) must be that user's name (`signal log` takes it when left out) and `--persona` must be granted where the command acts (for `new` and `intake`, `business_owner` unless another is named). A refusal prints why on stderr and exits 2 |
| The MCP server | Still reads and proposals only. It refuses to start for a local user who is not in the file, or with a `--person` that is not theirs, and each proposal needs the persona granted on its project. Proposals record the operator's identity |
| The kernel | Every card and question decision, and every pause and resume, is checked again: it stands only when the verified identity signing it holds the persona on that project |

Each decision records the identity beside the person: in the canon's `decisions.json`, in the ledger's
`decision` record, and in the cockpit's `cockpit_write` record.

**What a recorded identity is worth.** The surfaces verify who is acting: the cockpit through the proxy
and its secret, the command line and the MCP server through the operating system. The kernel's own check
trusts the identity that the process carrying out the write set, and writes other than decisions, pause
and resume are checked only by the surface that takes them. So the identity beside a person is only as
strong as the factory home's file permissions: any code that runs as an account that can write the home
(the cockpit's account, an operator's, or a process one of them started) can write a record that names
any identity, with the ledger's hash chain intact. Keep the home writable only by the accounts that run
Rihmasto, and run nothing else as them.

**`rihmasto intake`** takes a request in someone's name and replaces the project's request, so it is
signed like `new`. The one exception is the cockpit's own job: when someone files a new project in the
cockpit, the cockpit records the request's sha256 in the project's ledger under that person's verified
identity, and the intake job, which runs as the cockpit's account, carries out that request and no
other, once, before the project has a request.

## Setting up an identity-aware proxy

The cockpit keeps listening on 127.0.0.1 only. The proxy runs on the same machine, beside it, and is
the only thing that reaches it. Whatever proxy IT chooses, it must:

1. Sign people in with the organisation's identity provider and refuse anyone else.
2. Set the user header (and, if used, the email and groups headers) from the verified sign-in, and
   strip any copy of those headers a client sent.
3. Add the shared secret header to every request it forwards to `http://127.0.0.1:<port>`.
4. Keep its own session cookie: the cockpit page sends cookies to its own origin for this, and sets or
   reads none itself.
5. Serve the cockpit over HTTPS at the `origin` the access file names.

Make the shared secret long and random, at least 32 characters:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in the environment of both the proxy and the cockpit, under the name the access file gives in
`secret_env`, and never in a file in the repository. Start the cockpit as usual
(`python -m cockpit.server --home <home>`); it prints the access mode when it starts.

The cockpit reads the secret once and then takes the variable out of its own environment, so no process
it starts inherits it: not a job, not the gate's run of a project's own tests (code a model or a
developer wrote), not a road's product and not a Gnomon call. The command line, the MCP server and the
embed server take it out of theirs before they start anything, and all of them do the same with
`RIHMASTO_PROXY_SECRET` whatever the file names. After changing the secret, start the cockpit again.

**Finding a person's identity.** Have the person sign in once. The cockpit refuses them with
"`<issuer>#<user>` is granted no persona in the access file"; copy that identity into `people` and add
a binding.

Vendor facts below were checked on 2026-11-23 against the pages listed under [Sources](#sources).
UNVERIFIED marks what those pages did not confirm.

### oauth2-proxy

[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) (documentation version 7.15.x) works with
every identity provider below. Its alpha configuration can inject request headers from the sign-in's
claims and from a secret, and by default strips a client's copy of a header it injects
(`preserveRequestValue` defaults to false). Load it with `--alpha-config`.

```yaml
# oauth2-proxy.yaml, loaded with: oauth2-proxy --alpha-config oauth2-proxy.yaml
server:
  bindAddress: http://127.0.0.1:4180        # put the TLS endpoint (or a load balancer) in front of it
upstreamConfig:
  upstreams:
    - id: rihmasto-cockpit
      path: /
      uri: http://127.0.0.1:8787
      passHostHeader: true
injectRequestHeaders:
  - name: X-Forwarded-User
    values:
      - claimSource:
          claim: user
  - name: X-Forwarded-Email
    values:
      - claimSource:
          claim: email
  - name: X-Forwarded-Groups
    values:
      - claimSource:
          claim: groups
  - name: X-Rihmasto-Proxy-Secret
    values:
      - secretSource:
          fromEnv: RIHMASTO_PROXY_SECRET
providers:
  - id: organisation
    provider: oidc
    clientID: ${OAUTH_CLIENT_ID}
    clientSecret: ${OAUTH_CLIENT_SECRET}
    oidcConfig:
      issuerURL: https://login.example.org
      groupsClaim: groups
```

Settings the alpha file does not cover stay command-line flags, for example
`--redirect-url=https://rihmasto.example.org/oauth2/callback`, `--email-domain=*` (any email the
provider vouches for; restrict sign-in with groups instead) and `--cookie-secret`. The documentation
says to drop `--pass-user-headers` and `--set-xauthrequest` when the alpha file sets the headers;
which other flags your version still takes beside it is UNVERIFIED, so check `oauth2-proxy --help`.

- The raw secret goes in both environments. oauth2-proxy reads a `fromEnv` secret source as it is
  (`GetSecretValue` returns `[]byte(os.Getenv(...))`; only `value` is base64), in
  [`pkg/apis/options/util/util.go`](https://github.com/oauth2-proxy/oauth2-proxy/blob/master/pkg/apis/options/util/util.go),
  and adds it to the header unchanged (`header.Add(name, string(value))`), in
  [`pkg/header/injector.go`](https://github.com/oauth2-proxy/oauth2-proxy/blob/master/pkg/header/injector.go).
- It sends a claim with several values, such as `groups`, as one header with the values joined by
  commas: see [Groups](#groups).
- The documentation does not say which claim fills `user` (UNVERIFIED); in OIDC the stable identifier
  is the subject. Use the identity the cockpit's first refusal names.
- Some documentation examples put `upstreams` at the top level instead of under `upstreamConfig`;
  check which your version expects (UNVERIFIED).

**Microsoft Entra ID.** The issuer is `https://login.microsoftonline.com/<tenant-id>/v2.0`. Enable the
groups claim on the app registration; tokens then carry up to 200 groups, identified by their object ids
(Microsoft's "Configure group claims and app roles in tokens"), so the bindings name group ids. Keep them:
a setting that sends names instead lets a group name with a comma pose as two groups. For people in more than 200 groups,
oauth2-proxy's own `entra-id` provider (shown in its documentation as `provider="entra-id"` in the
configuration file) asks Microsoft Graph with the `User.Read` scope; without that, such a user signs
in with no groups. The `provider` value for Entra ID in the alpha file is UNVERIFIED: the generic
`oidc` provider with the issuer above works for up to 200 groups.

**Okta.** Use the generic `oidc` provider with the authorization server's issuer, such as
`https://<your-okta-domain>/oauth2/default`. Putting groups in the token needs a groups claim on
Okta's authorization server (UNVERIFIED: not checked against Okta's documentation); without it, bind
people by subject.

**Google.** Use `provider: google`; the issuer for the access file is `https://accounts.google.com`.
oauth2-proxy checks Google Workspace group membership through the Admin SDK (a service account with
domain-wide delegation, `--google-group`, `--google-admin-email`) to decide who may sign in, but its
documentation does not say whether the groups are passed on (UNVERIFIED), so bind Google users by
subject.

**Keycloak.** Use `provider: keycloak-oidc` with the issuer `https://<keycloak host>/realms/<realm>`
(`/auth/realms/<realm>` before Keycloak 17). oauth2-proxy's Keycloak page asks for two things on the
client:

- **An audience mapper.** Under Clients, your client, Client scopes, `<client id>-dedicated`, configure
  a new mapper of type Audience, set Included Client Audience to the client's id, and turn on both "Add
  to ID token" and "Add to access token".
- **Groups.** Create a client scope named `groups` with a Group Membership mapper whose token claim
  name is `groups`, and add it to the client. The page adds it as Optional, and an optional scope only
  reaches the token when it is asked for: oauth2-proxy's OIDC default scope is `openid email profile`,
  and it adds `groups` only when `allowedGroups` is set (`oidcDefaultScope` in
  [`providers/oidc.go`](https://github.com/oauth2-proxy/oauth2-proxy/blob/master/providers/oidc.go)).
  So ask for it on the provider, `scope: openid email profile groups`, or add the scope to the client
  as Default. Without it, group bindings never match.

With "Full group path" on, groups arrive as `/groupname`, and the bindings must name them that way.

### Google Cloud Identity-Aware Proxy

IAP adds `X-Goog-Authenticated-User-Id` and `X-Goog-Authenticated-User-Email`, whose values carry the
`accounts.google.com:` prefix, and a signed `x-goog-iap-jwt-assertion`. Google says not to rely on the
plain headers as a security mechanism, and to verify the signed header instead. Rihmasto's kernel uses
the standard library only and does not verify that signature. So IAP needs a verifying hop on the
cockpit's machine, which Rihmasto does not ship: it checks `x-goog-iap-jwt-assertion`, sets the user
header from it, strips anything a client sent, and adds the shared secret. IAP passes no groups header,
so bind people by subject. The identity then reads `<issuer>#accounts.google.com:<id>`, with the issuer
you put in the access file. The signing algorithm and the JWT's issuer value are UNVERIFIED here: the
page checked defers them to Google's signed-headers guide. Running oauth2-proxy with `provider: google`
instead avoids the extra hop.

### AWS Application Load Balancer with OIDC

An HTTPS listener rule can authenticate people with `authenticate-oidc` (any OIDC provider whose
endpoints are publicly resolvable) or `authenticate-cognito` (an Amazon Cognito user pool, with an app
client that has a secret and uses the code grant). The load balancer then forwards `x-amzn-oidc-data`
(the user's claims as a JWT signed with ES256), and two legacy unsigned headers, `x-amzn-oidc-identity`
(the subject) and `x-amzn-oidc-accesstoken`. AWS says to verify the signature of `x-amzn-oidc-data` and
its `signer` field before authorising anyone, and to let targets receive traffic only from the load
balancer's security group.

Rihmasto does not verify ES256 signatures, so, as with IAP, a verifying hop on the cockpit's machine
must check `x-amzn-oidc-data`, set the user header from its `sub`, strip client copies and add the
shared secret. AWS points to its AWS JWT Verify library for the check. Whether the load balancer itself
can add a fixed header to forwarded requests is UNVERIFIED. Using AWS IAM Identity Center as the OIDC
provider of an ALB is UNVERIFIED: it was not confirmed in AWS's documentation. With Cognito, the issuer
in the access file is the user pool's issuer.

## What phase A does not do yet

- **Joiners and leavers.** Nobody is provisioned or removed automatically. SCIM 2.0, so that a leaver
  loses their personas and their open cards re-route, is the next phase.
- **Separation of duties.** One person may still, for example, ask for a change and accept it.
- **Unsigned operator commands.** Commands that take no person (`run`, `deliver`, `tick`, `apply`,
  `operate`, `learn`, `sync`, `observe`, `updates apply`) run as the machine's operator, guarded by the
  factory home's file permissions. `rihmasto intake` is signed (see
  [What is checked where](#what-is-checked-where)).
- **Reads.** Any identity the file grants a persona can read every project's views; only writes are
  checked per project.
- **Integrity.** The access file is only as safe as its folder's permissions, and every recorded
  identity is only as strong as the factory home's file permissions (see
  [What a recorded identity is worth](#what-is-checked-where)). Rihmasto records every change, what the
  file claims about who made it and who owns it, but it cannot stop an administrator of the machine.

## Sources

Checked on 2026-11-23.

- oauth2-proxy, configuration overview (7.15.x):
  <https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview>
- oauth2-proxy, alpha configuration (7.15.x):
  <https://oauth2-proxy.github.io/oauth2-proxy/configuration/alpha-config>
- oauth2-proxy, Microsoft Entra ID provider:
  <https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/ms_entra_id>
- oauth2-proxy, OpenID Connect provider (with the Okta example):
  <https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/openid_connect>
- oauth2-proxy, Google provider: <https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/google>
- oauth2-proxy, Keycloak OIDC provider:
  <https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/keycloak_oidc>
- oauth2-proxy source (master branch): `pkg/apis/options/util/util.go`, `pkg/header/injector.go`,
  `pkg/middleware/headers.go` and `providers/oidc.go`, at <https://github.com/oauth2-proxy/oauth2-proxy>
- Microsoft, configure group claims and app roles in tokens:
  <https://learn.microsoft.com/en-us/security/zero-trust/develop/configure-tokens-group-claims-app-roles>
- Google Cloud, getting the user's identity with IAP: <https://docs.cloud.google.com/iap/docs/identity-howto>
- AWS, authenticate users using an Application Load Balancer:
  <https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html>
