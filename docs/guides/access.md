# Access: who may decide, and as which persona

Every decision in Rihmasto names a person and a persona. This guide explains how Rihmasto knows that
the person is who they say, which personas they may act as, and where code that a model or a developer
wrote runs while access is enforced. The decision behind it is
[D-0016](../../decisions/D-0016-access-through-the-organisations-identity.md); the code is
`kernel/access.py`, with `kernel/access_tokens.py` and `kernel/jwt_verify.py` (the sign-in) and
`kernel/access_isolation.py` (where untrusted code runs).

Rihmasto never stores passwords, and the cockpit holds no shared secret. People sign in through the
organisation's own identity provider (OIDC), at an identity-aware proxy that IT runs in front of the
cockpit. The proxy forwards the token the identity provider signed, and the cockpit checks that
signature itself with the provider's public keys. Who may act as which persona is a small file that IT
owns.

**Built:** both modes, the access file, the signed-token sign-in (RS256 and ES256, with presets for
oauth2-proxy, Google IAP, AWS Application Load Balancer and any OIDC proxy), groups from the token's
own claim, sessions that end with the token, the isolation runner (a container or a separate account)
for the gate's tests, adoption's baseline, local products and Gnomon cells, the scrubbed lane `.git`
(no repository inside a lane, no link under `tests/` followed, no replace ref or graft), names from a
token that never pass for a listed person's (lookalike letters and invisible characters included), a
key file of public keys only,
`rihmasto access check` and `rihmasto access keys`, and a record of every change in the factory ledger.
**Planned:** SCIM provisioning, separation of duties and a test run of the separate account on Linux
(see [Not built yet](#not-built-yet)).

## The two modes

| | single operator | enforced |
|---|---|---|
| When | no access file (the default) | `projects/_factory/access/access.json` with `"mode": "enforced"` |
| Who signs | whoever holds the cockpit session or the command line types a name | the identity the organisation's sign-in verified, or the local user on the operator's machine |
| Personas | any persona can be picked | only the personas the access file grants on that project |
| Untrusted code | runs as the operator's account, as before | runs only through the isolation runner the file names ([Isolation](#isolation)) |
| The cockpit says | "single operator: personas are self-declared" | "enforced: signed in as <name>" |

**Single operator** is how Rihmasto has always worked, and nothing about it changes. It suits one
person on their own machine, or a demo. The cockpit's header, the person menu and `rihmasto status`
say plainly that personas are self-declared.

**Enforced** is for a team. Each decision is signed by a verified identity, as a persona that a
binding in the access file grants on that project. The card-kind rules still apply on top: a person
granted `it` on a project still decides only the cards an `it` persona may decide.

## How a person's personas are resolved

1. **Who is it?** In the cockpit, the identity is `<issuer>#<subject>`: the issuer from the access
   file and the subject from the signed token (its `sub` claim, unless `proxy.subject_claim` names
   another, such as Entra ID's `oid`). On the operator's own machine, the command line and the MCP
   server use `local:<os user>`, the operating system account that runs them. It is read from the
   operating system, never from an environment variable such as `USERNAME`, which anyone can set.
2. **What is their name?** The name in the access file's `people` list. For someone the file does not
   list, the cockpit uses the token's `email` claim (or the claim `proxy.name_claim` names). This is
   the name every record carries; a typed name that differs is refused. A token's name that looks like
   the name of someone the file lists under another identity is not taken as it is, and neither is one
   that hides an invisible character or mixes lookalike scripts (see **Lookalike names.** below): the
   subject follows it, without the invisible characters, as in "Aino Example (stranger-sub)". So nobody
   whom a group lets in can record a decision under a listed person's name, and the name checks that
   follow (who may decide a trial's card, who submitted a change) never mistake one for the other. To
   give such a person their plain name, IT lists their identity in `people`.

   **Lookalike names.** A name claim can be one its holder edits (Keycloak's account console, an
   editable Okta profile field), so "looks like" is more than case and spacing. Rihmasto compares names
   by their skeleton (`kernel/name_skeleton.py`, after Unicode's confusable detection, UTS #39, reduced
   to what the standard library can do without its data file): compatibility forms folded, accents,
   zero-width characters, joiners and direction marks dropped, case folded, Cyrillic, Greek and
   Armenian letters that look like Latin ones read as those, `0` as `o` and `1`, `l` or `|` as `i`.
   "Aino Example" spelled with a Cyrillic A, or with a zero-width space inside it, is therefore Aino
   Example's name. A name that holds an invisible character, or mixes Latin, Cyrillic, Greek or Armenian
   letters, carries its subject whoever it resembles. A name in one script that nobody listed holds, such
   as "Νίκος Παπάς" or "José García", is taken as it is.
3. **Which personas?** Every binding that names the identity as its `subject`, or names one of the
   groups in the token's groups claim, grants its persona on its scope. A scope is `"*"` (every
   project, including the factory's own records, `_factory`) or a list of project ids. See
   [Groups](#groups).
4. **Where?** A write on a project needs the persona granted on that project. The factory's own
   writes (signals, concepts, embeds, new projects, the factory's autonomy cap) need it on `_factory`.
   A layout or a question to the assistant, which belong to no project, needs the persona granted
   anywhere.

Someone the proxy lets through but the file grants nothing is refused at sign-in. The refusal names
their identity, so IT can copy it into the file.

## The access file

It lives in a folder of its own in the factory home: `projects/_factory/access/access.json`, with the
identity provider's public keys beside it (`jwks.json`). Rihmasto only reads that folder; it never
writes in it, not even a lock file. So give write permission on that folder to IT alone, and read
permission to the accounts that run the cockpit, the command line and the MCP server. The folder above
it, `projects/_factory`, must stay writable by those accounts: the factory ledger, the signals, the
factory's canon and their lock files live there, and every signed write uses them.

On Linux or macOS, with an IT account `itadmin` and the operators' group `rihmasto`:

```sh
install -d -o itadmin -g rihmasto -m 0755 <home>/projects/_factory/access
install -o itadmin -g rihmasto -m 0644 access.json jwks.json <home>/projects/_factory/access/
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
    "preset": "oauth2-proxy",
    "issuer": "https://login.example.org",
    "origin": "https://rihmasto.example.org",
    "audience": "rihmasto-cockpit",
    "groups_claim": "groups"
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
    {"group": "0b8e5c1a-3d55-4a51-9b1e-6f2a1c4d7e90", "persona": "operations", "scope": "*", "note": "the on-call team"}
  ],
  "isolation": {"runner": "container", "image": "python:3.12-slim"}
}
```

| Field | What it holds |
|---|---|
| `schema` | always `rihmasto.access/1` |
| `mode` | `enforced`, or `single_operator` (then only `changed_by` and `note` may follow) |
| `changed_by` | who IT says changed the file last. In enforced mode, an identity in `people` that a subject binding grants `it` on `"*"`; in single-operator mode, a person's name. It is the file's own claim: the ledger records it as `claimed_by`, beside the file's owner |
| `proxy.preset` | the kind of sign-in proxy: `oauth2-proxy`, `google-iap`, `aws-alb` or `oidc` (any other OIDC proxy). It fixes the header the token arrives in, the algorithms it may be signed with and, for Google IAP, the issuer ([Presets](#presets)) |
| `proxy.issuer` | the identity provider's issuer, `https://` with no query or fragment: the token's `iss` must be exactly this, and it starts every proxied identity |
| `proxy.origin` | the address people open, such as `https://rihmasto.example.org`, with no path. The cockpit accepts this `Host` and `Origin` beside its own |
| `proxy.audience` | who the token is issued for, usually the client id of the app registration: the token's `aud` must hold it. For AWS ALB it is the client id the token's header names |
| `proxy.algorithm` | optional: `RS256` or `ES256`, among those the preset allows (the preset's first by default). The cockpit takes this, never what the token's header says; `none` and `HS*` are never accepted |
| `proxy.token_header` | optional: the header the token arrives in, when the preset allows more than one (oauth2-proxy: `Authorization`, the default, or `X-Forwarded-Access-Token`); required for `oidc` |
| `proxy.keys` | optional: the key file's name in the access folder (`jwks.json` by default) |
| `proxy.subject_claim`, `proxy.name_claim`, `proxy.groups_claim` | optional: the claims that give the subject (`sub`), the name (`email`) and the groups (none unless named). A name with dots that is not a claim itself is read as a path, such as Keycloak's `realm_access.roles` |
| `proxy.signer` | AWS ALB only: the load balancer's ARN, which its token's header must name |
| `proxy.clock_skew` | optional: seconds of clock difference allowed on `exp`, `nbf` and `iat` (0 to 300, 60 by default) |
| `people` | `identity` and `name`: who is who. An identity is `local:<os user>` or `<issuer>#<subject>` |
| `bindings` | a `subject` (a listed identity) or a `group`, a `persona` and a `scope` (`"*"` or a list of project ids); `note` is optional |
| `isolation` | where untrusted code runs while access is enforced: a container or a separate account ([Isolation](#isolation)) |

The file is checked whole and strictly: an unknown key, a header the cockpit reads for itself (such as
`Host`, `Cookie` or `X-Rihmasto-Session`), an algorithm the preset does not allow, an unknown persona,
an empty scope, a binding to an identity not in `people`, or a `changed_by` who is not IT on every
project makes the file invalid. A file written for the shared-secret proxy of the first release
(`user_header`, `email_header`, `groups_header`, `secret_header` or `secret_env`) is invalid too, and the
message says to name a preset, the audience and the key file instead.

**The key file** is the identity provider's JSON Web Key Set: its public signing keys, each with its
key id (`kid`). The cockpit takes RSA keys of at least 2048 bits and P-256 keys, and refuses a file that
holds a symmetric key or a key with private members (`d`, `p`, `q`, `dp`, `dq`, `qi`, `oth`): whoever
could read such a file could sign tokens, and the cockpit is meant to hold nothing that lets anyone do
that. Paste the provider's published JWKS, never a key pair. It reads the file again whenever it changes, so when the provider rotates its
keys, IT replaces the file and the next request uses the new keys. While the file is missing or not
usable nobody can sign in to the cockpit, and the refusal says why; the command line and the MCP
server, which sign as the local user, work on. Rihmasto never fetches keys over the network itself: IT
copies them in (a scheduled job of IT's own works), and every change is on record.

A request that carries the token header more than once is refused. The proxy sets it once; a proxy
that appended its value to a copy the client sent, instead of replacing it, would otherwise let the
client choose who it is.

### Groups

The groups come from the token's own claim, signed by the identity provider: a JSON list, each name
whole, so a comma is part of a group's name. A group named `x,rihmasto-ops` is that one group and never
`rihmasto-ops`. Name the claim in `proxy.groups_claim`:

| Provider | Claim | Notes |
|---|---|---|
| Microsoft Entra ID | `groups` or `roles` | `groups` carries the groups' object ids (GUIDs) unless the app registration is set to send names; `roles` carries the app roles assigned to the person. Name `oid` as `subject_claim` for an id that is the same in every app of the tenant |
| Okta | `groups` | a groups claim the authorization server is configured to add (UNVERIFIED: not checked against Okta's documentation) |
| Keycloak | `groups`, or `realm_access.roles` | the Group Membership mapper's claim; realm roles by path |
| Amazon Cognito | `cognito:groups` | in Cognito's ID and access tokens |
| Google IAP | none | IAP's token carries no groups: bind people by subject |

**Bind groups by an id that no user can choose**, never by a name someone outside IT can pick. With
Entra ID keep the object ids, or use app roles, which only an administrator assigns. When a person is in
more groups than the token can carry (Entra ID sends at most 200 groups in a token), the provider leaves
the groups claim out: such a person signs in with no groups. Bind them by subject, or use app roles.

### Changing it

- **Every change is on record.** The first time a write loads a changed access file or key file,
  Rihmasto appends an `access_changed` record to the factory ledger (`projects/_factory/ledger.jsonl`).
  The cockpit also records it when it starts. The record holds:
  - `sha256` and `previous`: the file's sha256 and the one before it; `mode`, `valid` and `error`;
  - `keys_sha256` and `keys_error`: the key file's sha256 as read, and why it cannot be used, if so;
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
| The cockpit | Identity only from the identity provider's signed token in the preset's header, verified with the key file: signature, algorithm, issuer, audience, expiry, not-before and issued-at. `/auth` opens a session for that identity; it answers that identity only and ends when the cockpit stops taking the token it was opened with (its expiry plus the clock skew). The session travels in `X-Rihmasto-Session`, so the token may use `Authorization`. When a session ends the page signs in again once through the proxy, which forwards a fresh token, before it asks the person. Every write route that takes a person or persona signs as the verified person and needs the persona granted on its project. The name field is read-only and the persona menu offers only the personas granted on the open project. A run or a new project starts only with an isolation runner named |
| The command line | Signed commands (listed [below](#which-commands-are-signed)) run as `local:<os user>`, which must be in the file. `--person` (for `new` and `intake`, `--requested-by`) must be that user's name (`signal log` takes it when left out) and `--persona` must be granted where the command acts (for `new` and `intake`, `business_owner` unless another is named). A refusal prints why on stderr and exits 2 |
| The MCP server | Still reads and proposals only. It refuses to start for a local user who is not in the file, or with a `--person` that is not theirs, and each proposal needs the persona granted on its project. Proposals record the operator's identity |
| The kernel | Every card and question decision, and every pause and resume, is checked again: it stands only when the verified identity signing it holds the persona on that project. The gate's test runs, adoption's baseline test run, products on the local road and Gnomon cells run only through the isolation runner, and the kernel's own git in a lane runs nothing the lane's `.git` names |

Each decision records the identity beside the person: in the canon's `decisions.json`, in the ledger's
`decision` record, and in the cockpit's `cockpit_write` record.

**What a recorded identity is worth.** The surfaces verify who is acting: the cockpit through the
provider's signed token, the command line and the MCP server through the operating system. Nothing the
cockpit's process holds lets anyone sign in as someone else: the key file is public and there is no
shared secret to read from its environment or memory. But the kernel's own check trusts the identity
that the process carrying out the write set, and writes other than decisions, pause and resume are
checked only by the surface that takes them. So the identity beside a person is only as strong as the
factory home's file permissions: any code that runs as an account that can write the home (the
cockpit's account, an operator's, or a process one of them started) can write a record that names any
identity, with the ledger's hash chain intact. That is why, with access enforced, code a model or a
developer wrote runs only through the [isolation runner](#isolation). Keep the home writable only by the
accounts that run Rihmasto, and run nothing else as them.

**`rihmasto intake`** takes a request in someone's name and replaces the project's request, so it is
signed like `new`, and the replacement is on record: a `request_replaced` record in the project's ledger
names who replaced it (and, with access enforced, their verified identity), the earlier requester, and
the sha256 of the request before and after. The one exception to the signing is the cockpit's own job:
when someone files a new project in the cockpit, the cockpit records the request's sha256 in the
project's ledger under that person's verified identity, and the intake job, which runs as the cockpit's
account, carries out that request and no other, once, before the project has a request.

### Which commands are signed

Every command of `rihmasto` is in exactly one of these lists; a test keeps them complete.

**Signed (60):** `adopt`, `answer`, `assess`, `assessment change`, `assume`, `autonomy set`,
`autopilot relay`, `autopilot start`, `autopilot stop`, `change`, `concept edit`, `connector disable`,
`connector enable`, `contract export`, `decide`, `delegation grant`, `delegation revoke`,
`embed create`, `embed revoke`, `evidence`, `hooks add`, `hooks remove`, `inputs refine`, `intake`,
`integration declare`, `integration withdraw`, `material add`, `models remove`, `models set`,
`modules set`, `new`, `output`, `pack`, `posture confirm`, `posture set`, `relay cockpit`,
`relay subscribe`, `relay unsubscribe`, `repo attach`, `repo contract`, `repo gate`, `repo holdouts`,
`repo releases`, `repo scan`, `rewind`, `security accept`, `security ingest`, `settings`, `shape`,
`shape attach`, `shape create`, `shape edit`, `shape say`, `shape start`, `signal log`,
`tracking digest`, `tracking look`, `tracking set`, `workspace open`, `workspace submit`.

**Unsigned (72):** `access check`, `access keys`, `apply`, `assessment compare`, `assessment list`,
`assessment show`, `autonomy show`, `autopilot run`, `autopilot status`, `build`, `capability check`,
`capability serve`, `catalogue`, `compile`, `concept apply`, `connector check`, `connector status`,
`connector validate`, `delegation list`, `delegation rules`, `deliver`, `demo`, `doctor`, `embed list`,
`graph answers`, `graph approvals`, `graph check`, `graph eval`, `graph impact`, `graph parity`,
`graph path`, `graph refuted`, `graph show`, `graph trace`, `hooks list`, `inputs read`,
`inputs summary`, `integration check`, `integration kinds`, `integration list`, `lanes`, `learn`,
`models list`, `models presets`, `models test`, `modules presets`, `modules show`, `next`, `observe`,
`operate`, `posture list`, `posture preview`, `posture show`, `relay list`, `relay log`, `relay run`,
`repo list`, `resurface`, `run`, `scan`, `security status`, `shape show`, `signal list`,
`signal triage`, `spec`, `square`, `status`, `sync`, `tick`, `track`, `updates apply`, `workspace list`.

An unsigned command takes no person. Many only read (`status`, `square`, `catalogue`, the `graph`
commands, the lists, `doctor`, `access check`); the others (`run`, `deliver`, `apply`, `tick`,
`operate`, `learn`, `sync`, `observe`, `updates apply` and the like) carry out what people already
decided, as the machine's operator, guarded by the factory home's file permissions. With access
enforced, the untrusted code they start goes through the isolation runner like everything else.

## Isolation

With access enforced, code that a model or a developer wrote never runs as the account that runs
Rihmasto: whatever that account can read, from the factory home to the cockpit's memory, code running
as it could read too. Four kinds of work go through the runner the access file names:

- **the gate's run of a project's own tests**;
- **adoption's baseline run** of an existing repository's own tests (`rihmasto adopt`). Without a runner
  the adoption goes ahead and its baseline reads "not measured", with the reason; the adopted code never
  runs;
- **a product on the local road** (an explore preview, or a local-process road);
- **a Gnomon cell**: every Gnomon call, whether a builder, the verifier, the analyst, the assistant or
  a website's chat.

Without a runner, or with one this machine cannot use, the kernel refuses that work and says why, and
the cockpit refuses to start a run or a new project's intake (a 403 that names the access file's
`isolation`). The person menu's access line says where untrusted code runs, and `rihmasto access check`
lists what would be refused. With a single operator nothing changes.

**A container** (`"runner": "container"`). The docker CLI (`docker_cli`, `docker` by default, as a list
of words; podman takes the same commands) runs the gate's suite in `image` with no network, no
capabilities (`--cap-drop ALL`, `no-new-privileges`), a read-only root, the project's checkout mounted
read-only at `/work`, and one writable folder for the outcomes; `python` names the interpreter in the
image (`python3` by default). A suite that outlives the gate's time is stopped and its container
removed. A product runs on a **docker road** instead of the local road: name one in `paved_roads.json`
for every environment, the explore preview's too. Gnomon runs as `cells` says: the command that runs
Gnomon in a container, where `{cwd}` stands for the cell's folder. Without `cells`, Gnomon cells are
refused.

```json
"isolation": {
  "runner": "container",
  "image": "python:3.12-slim",
  "cells": ["docker", "run", "--rm", "-i", "--volume", "{cwd}:{cwd}", "--workdir", "{cwd}",
            "registry.example.org/gnomon:0.6.6", "gnomon"]
}
```

**A separate account** (`"runner": "os_account"`, Linux and macOS). Rihmasto runs the work through
`sudo -n -u <account>`, giving a suite only its data and outcome folders, and a product only its own
variables (`HOST`, `PORT`, `DATA_DIR`, `TRAFFIC_LOG`, `APP_VERSION`) and write access to its data folder
and traffic log. Gnomon runs as that account too, unless `cells` names another command. A builder writes
in its lane, so IT gives the account write access to each lane folder (`lanes/lane-1` and so on, and
`lanes/analyst`) and nothing else of the factory home: not the lanes' parent folder, where the leases
and locks are, and not the factory home. Both accounts must be able to remove what the other wrote, so
use default ACLs (or a shared group with the setgid bit). A cell's task file is made readable to that
group (mode 0640), never to everyone. Adoption's baseline runs as the account too, reading the
checkout:

```sh
useradd --system --create-home rihmasto-run
echo 'rihmasto ALL=(rihmasto-run) NOPASSWD: ALL' > /etc/sudoers.d/rihmasto-run
for lane in ~rihmasto/gf-lanes/lane-1 ~rihmasto/gf-lanes/lane-2 ~rihmasto/gf-lanes/lane-3 ~rihmasto/gf-lanes/analyst; do
  mkdir -p "$lane"
  setfacl -R -m u:rihmasto-run:rwX,u:rihmasto:rwX "$lane"
  setfacl -R -d -m u:rihmasto-run:rwX,u:rihmasto:rwX "$lane"
done
```

```json
"isolation": {"runner": "os_account", "account": "rihmasto-run", "python": "/usr/bin/python3"}
```

The separate account is built, and its commands are tested for their shape; the tests have not run it
on Linux or macOS yet (planned). On Windows a separate account is refused (sudo there cannot run a
command as another account); name a container runner.

**The lane's `.git`.** A cell writes in its lane, and a container that mounts the lane, or a separate
account that may write there, can write the lane's `.git` too: a hook, `core.fsmonitor`, a filter or
diff driver, a signing program, or an origin pointing at a repository whose hooks it wrote. The kernel
runs git in the lane as Rihmasto's own account (to commit the cell's work, to push it, to check out the
next task, and in the gate), so before it does, it scrubs the lane (`kernel/git_guard.py`): the config
keeps only the keys a clone sets (origin the product repository again, includes and worktree configs
gone), every hook file is removed, a linked `config`, `hooks` or `info` is unlinked, never followed, and
a `commondir` file (which would send git to another repository's config and hooks) is removed. Every
kernel git call there also names an empty hooks folder of its own and turns fsmonitor, signing and
submodule recursion off, and git push or fetch in a lane runs only after the kernel set its origin. A
lane whose `.git` was replaced by a link or a `gitdir:` file is cloned anew.

**A repository inside the lane.** A cell can also make a repository of its own inside the lane (a
`sub/.git` with a filter driver in its config, recorded as a gitlink): `git status` and `git add` then
look inside it and run that filter. So before the kernel commits a cell's work, or lists what it
changed, it looks for a `.git` anywhere below the lane's top (without following a link) and for a gitlink
in the index or the head; if there is one, the work is refused and says where ("lane-1 holds a
repository inside it (sub, sub/.git)"). A cell writes plain files only. A gitlink the product already
holds (an adopted repository's own submodule) stays allowed: the kernel never checks a submodule out,
so its folder is empty, and a `.git` that appears in it is refused like any other. The kernel's git also
ignores submodules outright (`diff.ignoreSubmodules=all`), but that alone is not enough: `git add`
still asks a submodule whether it changed, which is why the refusal comes first.

**The next checkout.** Before the next task's checkout, every `.git` below the lane's top is removed,
the checkout throws away every change to a tracked file (`checkout -f`), and `git clean -ffdx` removes
what is left, nested folders included. The next task starts from the product repository's own branch,
read from the product repository (`git ls-remote`), never from the lane's `refs/remotes`, so a moved
remote ref or a changed fetch refspec is never the next base; origin's fetch refspec is git's default
again after every scrub.

**What the kernel's git sees.** A replace ref (`refs/replace/*`) or a graft (`.git/info/grafts`) makes
git show one commit as another: the gate's protected-file check would see the base's tree while the push
sent the real commit, or the fail-first check would check out a broken base. The scrub removes replace
refs (loose and packed), grafts, a `shallow` file and object alternates, and every kernel git call there
turns replace refs off (`core.useReplaceRefs=false`, `GIT_NO_REPLACE_OBJECTS=1`) and reads an empty
grafts file of its own (`GIT_GRAFT_FILE`), including the protected-file check.

**Links under `tests/`.** The gate's fail-first and template checks run the head's tests on the base.
It takes them from the head commit in git (`git checkout <head> -- tests` in its base worktree), never
by copying the lane's files: a link or a Windows junction a cell left under `tests/`, pointing at
something only Rihmasto's account can read, is never followed, so its target never reaches the isolated
suite. A link the head commits stays a link, which the isolated suite cannot follow.

With all of this, a poisoned lane does not carry over to the next task or project: its `.git` is
scrubbed or the lane cloned anew, nested repositories and tracked-file changes are gone, and the base
comes from the product repository.

### Tutorial: see the isolation work

1. **Without a runner.** In a factory with access enforced and no `isolation`, run
   `rihmasto access check`: it says the gate's test runs, local products and Gnomon cells are refused,
   and adoption's baseline is not run.
   Adopt a small repository: `rihmasto adopt --person "<your name>" --persona business_owner --source
   <path> --intent maintain Trial`. It is adopted, and `projects/<id>/baseline.json` reads "not
   measured" with the reason; nothing of the repository ran.
2. **With a container.** Add `"isolation": {"runner": "container", "image": "python:3.12-slim"}` and
   adopt again: the baseline now runs in a container with no network and the checkout read-only.
3. **The lanes.** After a run, open a lane's `.git/config`: it holds only the keys a clone sets, and
   `.git/hooks` holds no hook.
4. **Ask Rihma** "where does untrusted code run?" or "what does the kernel do with a lane's .git?": it
   takes you to the access note in the person menu.

### Tutorial: see a nested repository refused

1. In a lane after a cell ran (or any clone of a product, standing in for one), make a repository
   inside it as a cell could: `git init sub`, commit a file there, then
   `git update-index --add --cacheinfo 160000,<sub's HEAD>,sub` in the lane.
2. Run the task again, or in Python: `Lane(Path("<lane>")).commit_all("try")`. It is refused with
   "holds a repository inside it (sub, sub/.git)", and nothing in `sub/.git/config` ran.
3. Start the next task in that lane: `sub/` is gone, every tracked file is the product's again, and the
   base is the product repository's `main`, whatever the lane's `refs/remotes/origin/main` said.
4. **Ask Rihma** "a nested repository in the lane?" or "a lookalike name in a token?": it takes you to
   the access note in the person menu.

## Setting up an identity-aware proxy

The cockpit keeps listening on 127.0.0.1 only. The proxy runs on the same machine, beside it, and is
the only thing that reaches it. Whatever proxy IT chooses, it must:

1. Sign people in with the organisation's identity provider and refuse anyone else.
2. Forward the identity provider's signed token on every request it passes to
   `http://127.0.0.1:<port>`, in the preset's header, replacing any copy a client sent.
3. Keep its own session cookie: the cockpit page sends cookies to its own origin for this, and sets or
   reads none itself.
4. Serve the cockpit over HTTPS at the `origin` the access file names.

There is no secret to share between the proxy and the cockpit. Put the provider's public keys in the
access folder as `jwks.json`, start the cockpit as usual (`python -m cockpit.server --home <home>`); it
prints the access mode, the preset and where untrusted code runs when it starts.

**Finding a person's identity.** Have the person sign in once. The cockpit refuses them with
"`<issuer>#<subject>` is granted no persona in the access file"; copy that identity into `people` and
add a binding. Or save a test user's token and run `rihmasto access check --token-file <file>`.

### Presets

Vendor facts here come from the vendors' documentation; the ones marked UNVERIFIED were not confirmed
against it. Before going live, check a real token with `rihmasto access check --token-file`: it shows
the identity, name, groups and personas the cockpit would sign that person in with, or why not.

| Preset | Header | Algorithm | What the file names |
|---|---|---|---|
| `oauth2-proxy` | `Authorization: Bearer <ID token>` (default), or `X-Forwarded-Access-Token` | RS256 (default) or ES256 | the provider's issuer; the client id as `audience` |
| `google-iap` | `x-goog-iap-jwt-assertion` | ES256 | issuer `https://cloud.google.com/iap`; the backend's audience |
| `aws-alb` | `x-amzn-oidc-data` | ES256 | the provider's issuer; the client id as `audience`; the load balancer's ARN as `signer` |
| `oidc` | the `token_header` the file names | RS256 (default) or ES256 | the provider's issuer and `audience` |

**oauth2-proxy.** Run it with `--pass-authorization-header`, which passes the OIDC ID token to the
cockpit as `Authorization: Bearer`; the cockpit's own session then travels in `X-Rihmasto-Session`.
`--pass-access-token` passes the OAuth access token in `X-Forwarded-Access-Token` instead: use it only
where the provider issues the access token as a JWT for this client (Keycloak can); Entra ID's access
tokens for Microsoft Graph are not meant to be verified by anyone else, so with Entra ID pass the ID
token. In the alpha configuration the same headers are set with `injectRequestHeaders` from the
session's `id_token` claim with the prefix `Bearer ` (UNVERIFIED: the conversion was not checked
against the alpha configuration's documentation). Settings the alpha file does not cover stay
command-line flags, for example `--redirect-url=https://rihmasto.example.org/oauth2/callback` and
`--cookie-secret`; check `oauth2-proxy --help` for your version.

```yaml
# oauth2-proxy.yaml, loaded with: oauth2-proxy --alpha-config oauth2-proxy.yaml --pass-authorization-header
server:
  bindAddress: http://127.0.0.1:4180        # put the TLS endpoint (or a load balancer) in front of it
upstreamConfig:
  upstreams:
    - id: rihmasto-cockpit
      path: /
      uri: http://127.0.0.1:8787
      passHostHeader: true
providers:
  - id: organisation
    provider: oidc
    clientID: ${OAUTH_CLIENT_ID}
    clientSecret: ${OAUTH_CLIENT_SECRET}
    oidcConfig:
      issuerURL: https://login.example.org
      groupsClaim: groups
```

The client secret above is oauth2-proxy's own, for the provider; the cockpit never sees it. Some
documentation examples put `upstreams` at the top level instead of under `upstreamConfig`; check which
your version expects (UNVERIFIED).

- **Microsoft Entra ID.** The issuer is `https://login.microsoftonline.com/<tenant-id>/v2.0` and the
  audience the app registration's client id. The keys are at
  `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys`. Use `"subject_claim": "oid"` for
  the person's object id (the `sub` differs per app) and `"name_claim": "preferred_username"` when the
  token carries no email. Groups: see [Groups](#groups).
- **Okta.** The issuer is the authorization server's, such as `https://<your-okta-domain>/oauth2/default`,
  with keys at `<issuer>/v1/keys`. Groups need a groups claim on the authorization server (UNVERIFIED);
  without it, bind people by subject.
- **Google, through oauth2-proxy.** Use `provider: google`; the issuer is `https://accounts.google.com`
  and the keys are Google's published OAuth keys (`https://www.googleapis.com/oauth2/v3/certs`). Whether
  oauth2-proxy passes Workspace groups on is UNVERIFIED, so bind Google users by subject.
- **Keycloak.** Use `provider: keycloak-oidc` with the issuer `https://<keycloak host>/realms/<realm>`
  (`/auth/realms/<realm>` before Keycloak 17); the keys are at
  `<issuer>/protocol/openid-connect/certs`. oauth2-proxy's Keycloak page asks for two things on the
  client:
  - **An audience mapper.** Under Clients, your client, Client scopes, `<client id>-dedicated`,
    configure a new mapper of type Audience, set Included Client Audience to the client's id, and turn
    on both "Add to ID token" and "Add to access token".
  - **Groups.** Create a client scope named `groups` with a Group Membership mapper whose token claim
    name is `groups`, and add it to the client. An optional scope only reaches the token when it is
    asked for, so ask for it on the provider, `scope: openid email profile groups`, or add the scope to
    the client as Default. With "Full group path" on, groups arrive as `/groupname`, and the bindings
    must name them that way.
- **Amazon Cognito, through oauth2-proxy.** The issuer is
  `https://cognito-idp.<region>.amazonaws.com/<user pool id>`, with keys at
  `<issuer>/.well-known/jwks.json`; the groups claim is `cognito:groups`.

**Google Cloud Identity-Aware Proxy** (`"preset": "google-iap"`). IAP signs `x-goog-iap-jwt-assertion`
with ES256, with the issuer `https://cloud.google.com/iap` and an audience that names the backend:
`/projects/<project number>/apps/<project id>` for App Engine, or
`/projects/<project number>/global/backendServices/<service id>` behind a load balancer. Its public keys
are published as a JWKS at `https://www.gstatic.com/iap/verify/public_key-jwk`. The subject reads
`accounts.google.com:<id>`, so an identity is `https://cloud.google.com/iap#accounts.google.com:<id>`.
IAP's plain headers (`X-Goog-Authenticated-User-Id`, `X-Goog-Authenticated-User-Email`) are never read:
Google says not to rely on them. IAP's token carries no groups; bind people by subject. (The audience
forms and the keys' address are from Google's signed-headers guide, not re-checked in this pass.)

**AWS Application Load Balancer** (`"preset": "aws-alb"`). A listener rule with `authenticate-oidc` (any
OIDC provider) or `authenticate-cognito` forwards `x-amzn-oidc-data`: the user's claims as a JWT signed
with ES256, whose header carries `alg`, `kid`, `signer` (the load balancer's ARN), `iss`, `client` (the
client id) and `exp`, and whose parts are base64url with padding. The cockpit checks the signature, that
`signer` is the ARN the file names and `client` the audience, and the issuer and expiry from the header.
The load balancer publishes each key as a PEM file at
`https://public-keys.auth.elb.<region>.amazonaws.com/<key id>`; turn those into the key file with
`rihmasto access keys <key id>=<file.pem>`. The unsigned `x-amzn-oidc-identity` and
`x-amzn-oidc-accesstoken` are never read. Let the cockpit's machine receive traffic only from the load
balancer. The groups the token carries depend on what the provider's user-info endpoint returns
(UNVERIFIED for Cognito's `cognito:groups`); without them, bind people by subject.

**Any other OIDC proxy** (`"preset": "oidc"`). Name the header it forwards the ID token in
(`token_header`), the issuer, the audience and, if the provider signs with ES256, the algorithm.

## Tutorial: turn access on for a team

This takes a factory from a single operator to enforced access. Every step is on record.

1. **Pick the preset and register the app.** In the identity provider, register the cockpit as an app
   (its redirect address is the proxy's) and note the issuer and the client id. Set up the proxy as
   [above](#setting-up-an-identity-aware-proxy).
2. **Write the key file.** Save the provider's JWKS as `projects/_factory/access/jwks.json`. For AWS
   ALB, fetch each key's PEM and run `rihmasto access keys <kid>=<file.pem> > jwks.json`.
3. **Write the access file** beside it: the preset, issuer, origin and audience; the people; the
   bindings (groups by id); and an isolation runner. Give the folder to IT alone.
4. **Check it before anyone signs in.** Save a test user's token as the proxy forwards it (an ID token
   for the same client, from the provider's own test tools) and run
   `rihmasto access check --token-file token.txt`. It prints the identity, name, groups and personas the
   cockpit would sign that person in with, the keys it read, where untrusted code would run, and exits 2
   when anything would be refused. It writes nothing.
5. **Start the cockpit** behind the proxy and open the `origin`. The top bar says "enforced: signed in
   as <name>"; the person menu shows the verified name, the personas granted on the open project, when
   the session ends, and where untrusted code runs.
6. **Ask Rihma.** "Who signs decisions here?" or "where does untrusted code run?" takes you to the
   access note.
7. **Look at the record.** `projects/_factory/ledger.jsonl` holds an `access_changed` record for the
   file and the keys; each decision names the verified identity beside the person.

## Not built yet

- **Joiners and leavers.** Nobody is provisioned or removed automatically. SCIM 2.0, so that a leaver
  loses their personas and their open cards re-route, is the next phase. Until then, removing a person
  from the access file ends their access at their next request; removing them from a group at the
  provider ends it when the token they hold expires, since the token carries their groups.
- **Separation of duties.** One person may still, for example, ask for a change and accept it.
- **Names of people the file does not list.** A token's name never passes for a listed person's, but two
  people whom only a group lets in could carry the same name if `name_claim` names a claim that is not
  unique (a display name). Keep the default `email`, or Entra ID's `preferred_username`, which the
  provider keeps unique; the identity beside each name always tells them apart. Lookalike names are
  compared by a skeleton built from a hand-made table of Cyrillic, Greek and Armenian letters, not
  Unicode's full confusables data (which Rihmasto does not ship); a lookalike from another script that
  the table lacks is caught only when it mixes scripts within the name.
- **The judged head.** The kernel pushes a warranted cell's branch, not the commit the gate judged, and
  a suite run as a separate account can write the lane's refs while the gate runs. Pushing the judged
  commit itself is planned (`kernel/dispatch.py`, another stream's file).
- **The separate account on Linux.** Its commands are tested for their shape on every machine, but the
  tests have not yet run work as a second account on Linux or macOS.
- **Fetching keys.** Rihmasto makes no network calls for keys; IT copies the provider's keys into the
  access folder when they rotate.
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
- Microsoft, configure group claims and app roles in tokens:
  <https://learn.microsoft.com/en-us/security/zero-trust/develop/configure-tokens-group-claims-app-roles>
- Google Cloud, getting the user's identity with IAP: <https://docs.cloud.google.com/iap/docs/identity-howto>
- Google Cloud, securing your app with signed headers: <https://docs.cloud.google.com/iap/docs/signed-headers-howto>
  (not re-checked in this pass)
- AWS, authenticate users using an Application Load Balancer:
  <https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html>
- RFC 7515 (JSON Web Signature), RFC 7517 (JSON Web Key), RFC 7518 (algorithms), RFC 8017 (PKCS #1)
  and RFC 6979 (deterministic ECDSA, whose P-256 test vectors the tests use).
