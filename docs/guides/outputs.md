# Outputs: what each audience receives

People expect different results from the same project. A developer wants a container to run, the
people who use the product want a web app they sign in to, an integrator wants an API description or
an MCP server, a business owner wants a plain report of what was done, a reviewer wants an evidence
pack, and a team wants the source on a branch of its own. Rihmasto calls each of these an **output
target**. A person chooses the targets; the kernel builds each one from the project's records and its
release, with no model, and records every choice and every build in the ledger with who asked.

## What is built, and what is planned

| Target | For | Holds | Status |
|---|---|---|---|
| `login_web_app` | the people who use it | the product with the paved road's sign-in, its checks, and `SIGN-IN.md` | built |
| `container` | a developer | the source at the release, its Dockerfile, `compose.yaml` on 127.0.0.1:8080, `image.json`, a README | built |
| `api` | an integrator | `openapi.json` (OpenAPI 3.1) from the product's routes, each operation with its criteria and their evidence | built |
| `mcp_server` | an integrator's agents | the product's operations as MCP tools | **planned**: it comes from the small-capability faces, through the hook below |
| `report` | a business owner | `report.html` and `report.md`, in plain language, every line naming its record | built |
| `evidence_pack` | a reviewer | the evidence pack of [packs and evidence](packs-and-evidence.md) | built (the existing export) |
| `source` | a team | `product.bundle`, the product's git history, with how to put it on a branch | built |

Built with it (FR-OUT7):

- **The factory's own checks and the sign-in.** The holdout runner, the probes and the shadow replay
  of recorded traffic carry no session. When the product's sign-in turns one of their requests away
  (401 with `"sign_in": "/sign-in"`) and the step expected something else, the scenario is recorded
  as **not measured**, with that reason, never as failed; a step that expects the 401 still passes,
  and a real mismatch still fails. A probe round counts it as neither a check nor a failure, and a
  shadow replay that met the sign-in is **not measured**, never passed; the canary leaves those
  requests out of its sample (`SIGNED_OUT` and its helpers in `kernel/holdouts.py`).
- **Intake knows the choice.** Outputs chosen with the new-project request are told to the intake
  panel, and a panel question they already settle (sign-in or single sign-on, for `login_web_app`) is
  not asked: a `question_not_asked` record keeps it, with the person who chose. The brief keeps the
  choice under **Outputs chosen [owner]**, as that person's word, and the spec is written from the
  brief.
- **The builder knows the sign-in.** When the product has it, the builder's envelope says how
  `req.user`, `require_role`, `csrf_field` and `session_headers` work, and that the road's sign-in
  files are never edited.

Also **planned**, not built:

- a test account for the holdout runner, the probes and the shadow replay, so a product with
  sign-in is measured end to end instead of not measured; until then its criteria rest on the
  product's own tests at the gate;
- choosing outputs in the cockpit's **New project** form and inside the intake panel's questions;
  today the choice is made in the Outputs view, on the command line, or with the new-project request
  of the cockpit's API;
- settling questions already asked when outputs are chosen after intake: today only intake reads the
  choice.

## Tutorial: choose, build and hand over (5 minutes, on the demo)

Build the demo and open the cockpit (`rihmasto demo`, then `rihmasto-cockpit --home var/demo`). Sign
in, press the person chip, type your name and pick **Business owner**.

1. **Find the view.** Open **Projects → Shipment webhook to the stock system**, then the **Outputs**
   tab. Or ask: press `/`, type "Where are the outputs?" and press **Take me there**.
2. **Read what each holds.** Seven cards, one per target, each with its audience, what it holds and
   whether it is ready. The MCP server card says **Planned**.
3. **Choose.** Nobody has chosen yet, so the work profile's proposal is ticked (container, API,
   report and source for an integration). It is a proposal, not a choice. Tick **Evidence pack**,
   untick **Source**, write why ("For the handover to the warehouse team") and press **Save the
   choice**. The card now says who chose, as which persona, and why. The ledger has an
   `outputs_chosen` record with what was chosen before.
4. **Build one.** On the **Delivery report** card press **Build and download**. A zip arrives with
   `report.html`, `report.md` and `MANIFEST.json`. Open `report.html`: what was asked and by whom,
   what was built, the decisions and who made them, the assumptions and whether anyone confirmed
   them, the evidence in plain words, how to try it, the cost (here "not measured": no model run was
   priced), and the known limits. Each line names the record it rests on.
5. **Build the rest.** Press **Build every chosen output**. Each card offers a **Download** link that
   works once. Build again and you get the same file name: the name is the content's sha256, and the
   same records always give the same bytes. (The evidence pack is the exception: each export is a
   fresh one, named by when.)
6. **Try a target you did not choose.** Its button says "Choose it first", and nothing is built.

The same from the command line:

```bash
rihmasto output <webhook>                                    # the targets, what each holds, the choice
rihmasto output <webhook> --choose container,api,report,evidence_pack \
         --reason "for the handover" --person "Aino Virtanen" --persona business_owner
rihmasto output <webhook> --target report --target container \
         --person "Aino Virtanen" --persona business_owner     # into <home>/exports
rihmasto output <webhook> --target api --release 1 --out ./handover --person ... --persona ...
```

A choice or a build without `--person` and `--persona` is refused (exit 2).

## Choosing

- **Who chooses:** a business owner, product owner, developer or IT. **Who builds:** those, and
  compliance. A persona outside them is refused with the kernel's reason, and nothing is recorded.
- **When:** at intake, by naming `outputs` in the cockpit's new-project request (`POST /api/projects`
  with `"outputs": ["report", "login_web_app"]`), recorded as chosen by the requester at intake; or
  at any time later, in the **Outputs** view or with `rihmasto output <pid> --choose`.
- **Changing it:** choose again. `outputs.json` in the project folder keeps the current choice and
  its history; each `outputs_chosen` record keeps who, as which persona, why, and what was added and
  removed.
- **Until someone chooses,** the work profile only proposes: a product proposes the container, the
  API, the report and the source; a capability pack adds the MCP server and the evidence pack; an ops
  agent's report proposes the report and the evidence pack (`OUTPUTS` in `kernel/profiles.py`).

## The web app with sign-in

Choosing `login_web_app` gives the product the paved road's sign-in (`kernel/scaffold_auth.py`):

- local accounts, each password a salted PBKDF2-SHA256 hash of 600,000 rounds, never stored or
  logged as text, and never written to the traffic log;
- a session cookie that is HttpOnly, SameSite=Lax, and Secure when the request came over TLS;
- a CSRF token on every form and every POST, PUT, PATCH and DELETE;
- after 5 failed sign-ins in a row the account waits 15 minutes, and the answer never says whether
  the name exists;
- the first admin from `FIRST_ADMIN_USER` and `FIRST_ADMIN_PASSWORD` at first start, taken out of the
  environment once read; the admin sets a new password at first sign-in and adds the other accounts;
- the organisation's own sign-in (OIDC) through an identity-aware proxy in front of the product, the
  pattern [access](access.md) sets up for the cockpit: `SIGN_IN_MODE=proxy` and a shared
  `SIGN_IN_PROXY_SECRET`; the user header and the secret header must each come exactly once;
- a Dockerfile that runs the service as an unprivileged user owning `/data`, whether the sign-in came
  with the first build or was added later.

Every request passes the sign-in's guard before its handler; `/health`, `/static/` and the sign-in
page stay open. `tests/test_road_sign_in.py` checks all of it and runs with the product's whole
suite at every gate. The road owns both files: the gate refuses a builder's change to either
(`PROTECTED` in `kernel/lanes.py`). The product's own `factory/SIGN-IN.md` tells the people who run
it how to set it up.

**When it is added.** Chosen before the contract is compiled, the product's repository starts with
it. Chosen later, the kernel adds it to the product's main, but only after the product's whole suite
passes with it, run as the gate runs it, the sign-in's own checks among them (`sign_in_added`, with
who chose, how many tests ran and how many sign-in checks passed); a product whose server predates the
sign-in hook is refused (`sign_in_refused`) and main does not move. Choose it before the build or
between builds: a cell working at that moment started from the main before it. The next release carries it.
The Dockerfile changes too: the service runs as the unprivileged user `10001`, as in a product with
sign-in from the start, so the red team's static rules scan it clean. A deployment's data volume made
before may still belong to root: `sign_in_added` records it, and the product's `factory/SIGN-IN.md`
gives the one command that hands the volume over. Dropping the target later is recorded, and the
sign-in stays until a change removes it.

**What the sign-in's checks cover.** Its checks run at every gate, and a weakened sign-in fails them:
a cheap hash, a missing CSRF check, no lockout, a cookie scripts can read, and session fixation (a
sign-in that keeps a session token sent with the request, made up or someone else's live session).

### Tutorial: choose the sign-in at intake (3 minutes, on the demo)

1. Start a project with the choice in its request. The cockpit's **New project** form does not offer
   outputs yet (planned); the cockpit's API does, for a script or a program that starts projects:
   `POST /api/projects` with `{"title": "Lab loans", "source": "Lend the lab's drills and ladders.",
   "requested_by": "Aino", "persona": "business_owner", "outputs": ["login_web_app", "report"]}`.
   The choice is recorded first (`outputs_chosen`, `when: intake`), then intake runs.
2. When intake is done, open **Questions**: nobody is asked whether single sign-on is required. The
   **Ledger** shows a `question_not_asked` record naming you, and the **Brief** lists the choice under
   **Outputs chosen [owner]**.
3. Once a release runs, open **Evidence**: a holdout the sign-in turned away says **not measured**,
   with the reason, never failed.

## The source output, step by step

Unzip the source output anywhere, outside any repository, and run its README's commands as written:
the clone names its branch (`git clone --branch main product.bundle <pid>`), `git bundle verify`
runs inside the clone (git needs a repository to verify a bundle), and the last two commands put the
release (or main's tip, with no release yet) on a branch of your team's repository. The bundle also
carries `HEAD`, so a plain `git clone product.bundle` checks main out too.

## What each build records

Every build, made or not, is an `output_built` record: the target, the release and revision, the
file and its sha256 (or why it was not built), and the person and persona who asked. The report
leaves these records out of what it reports, so it reads the same however often outputs are built.
Each zip holds `MANIFEST.json` with the sha256 of every file, and every entry carries a fixed time.
In the cockpit, a built file is handed over through a link that works once.

## The hook for the MCP server

The MCP server, and later the other small-capability faces, come from `kernel/faces.py`, built in
parallel. Rihmasto's outputs call one function there when it exists:

```python
def output_files(project, release: dict | None, face: str) -> dict[str, str | bytes]:
    """The files of ``face`` ("mcp_server") for this project and release, by name; {} when it has none."""
```

Until that function exists the target is **planned**, shown so, and a build of it says why
(`FACES_MODULE` and `FACES_HOOK` in `kernel/output_builders.py`).

## The hook for postures

A posture (prototype, balanced, production, regulated; `kernel/posture.py`, built in parallel) may
propose outputs, never choose them. When that module offers

```python
def proposed_outputs(project) -> list[str] | None:
    """The output targets this project's posture proposes, or None to leave it to the work profile."""
```

its proposal replaces the work profile's in the Outputs view, ticked as a proposal until a person
saves a choice. A proposal naming a target that does not exist is ignored. Nothing is recorded until
a person chooses (`POSTURE_MODULE` and `POSTURE_HOOK` in `kernel/outputs.py`).

## Where it lives

| Piece | File |
|---|---|
| targets, choosing, building, the command | `kernel/outputs.py` |
| what each target holds | `kernel/output_builders.py` |
| the delivery report | `kernel/report.py` |
| the sign-in and its checks | `kernel/scaffold_auth.py`, `kernel/scaffold_auth_tests.py` |
| the guard hook in the product's server | `kernel/scaffold.py` (`guard`, `respond`) |
| the Outputs view | `cockpit/static/outputs.js`, `GET/PUT /api/projects/<pid>/outputs`, `POST .../outputs/build` |
| the sign-in and the factory's checks | `kernel/holdouts.py` (`SIGNED_OUT`), `kernel/operate.py` |
| what intake and the builder are told | `GIVEN`, `asked_again`, `brief_lines`, `builder_notes` in `kernel/outputs.py` |
| the criteria | `FR-OUT1` to `FR-OUT7` in `contract/contract.json` |
