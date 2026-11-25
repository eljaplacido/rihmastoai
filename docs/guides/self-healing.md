# Self-healing: incidents, remedies and what Rihmasto learned

Rihmasto is built on resilience and antifragility ([D-0018](../../decisions/D-0018-resilience-and-antifragility.md),
[D-0024](../../decisions/D-0024-self-healing-simple-for-one-governed-for-many.md)). A failure should not leave you
stuck. Rihmasto records it, says what happened, offers what it knows will fix it, and learns from what did.
Nothing is fixed silently: every step is recorded, and anything that changes code or policy waits for a person.

## Incidents

These become an **incident**:

- a server error (a 500);
- a background job that failed, or one lost when the cockpit restarted;
- a cockpit action that failed, or a refused step you did not expect;
- a view that broke while drawing, or came back empty;
- a confidential project's step refused because a role is hosted;
- a check, automation or cell runner that failed;
- a scan that could only read part of a folder;
- an IDE agent's failure that your agent observability hub saw it not recover from: the hub project and the
  session ids are its context, and **Open Agent sessions** its remedy
  ([agent-observability.md](agent-observability.md));
- a Gnomon audit that failed, with its findings (id, severity, title, evidence, new) as context, or one of
  Rihma's role evals where a model answered some cases wrongly, with each wrong case
  ([audits-and-evals.md](audits-and-evals.md)). An audit that keeps failing is one incident with its count;
- your own report: **Something's wrong here**, at the foot of every view.

Each incident has:

- **A fingerprint.** It is built from the kind, where it happened (a route, a view, a job's kind), the error's
  class and its message. Ids, numbers, paths, addresses, quoted values and anything that looks like a secret are
  taken out first, so the same failure has the same fingerprint wherever it happens.
- **Its context.** This is the view and the route, a summary of the request (its keys, never the body of a
  secret), the server log lines around it, a job's log tail, the ledger records involved and the persona. Every
  string is masked.
- **A record.** `incident_opened` goes into the project's ledger, or the factory's own when no project is
  involved. The contents are kept in `heal/incidents/I-0001.json` under the factory home.

The same failure is counted on its open incident, not opened again. An incident moves through these states:

1. **open**
2. **investigating**
3. **fixed**
4. **learned**, once what fixed it is approved as a remedy

## Never a dead end

When a view cannot load or draw, the cockpit shows a panel instead of a bare error. The panel says what happened
in plain words and offers:

- **Try again**;
- the remedies Rihmasto knows;
- **Investigate with Rihma**;
- the incident's id.

When an action fails, its message offers the same way on, or **I did not expect this** to report it. An error
the page did not catch is reported too, signed with the name in the person chip. The server records its own
errors whatever the page does.

## Remedies

### Built-in

Rihmasto knows remedies for these classes of failure:

| What happened | Offered |
| --- | --- |
| The product is not running (the Try view, Releases) | Start it on its road, Why it is not running |
| A model endpoint did not answer | Open Models setup, Use the coding agent you already have |
| A folder is outside the folders the cockpit may read | Allow it: how to add it to `RIHMASTO_SOURCE_ROOTS` |
| A confidential project refused a hosted model | Use my local model |
| A job was lost on a restart, or failed | Run it again (the same request), Open the job's log |
| A tool a check needs is missing | How to install it; the check stays not measured |
| A view broke, or the cockpit hit a bug | Try again |

**Investigate with Rihma** is always offered.

### Learned

When you resolve an incident with **This fixed it** (or **Try again** worked), Rihmasto proposes what fixed it
as a remedy for that fingerprint. A person approves it once, as IT, a developer, operations, a product owner or a
business owner. The approval records a hash of the remedy it approved.

**Solo and team.** In solo mode the person named on the first visit holds every persona, so they approve a
remedy, a feedback proposal and a pull request (Rihmasto's own included) whichever persona they look through. In
team mode the persona must be one that may approve, and the cockpit signs only with a persona your user, groups or
project roles grant ([access.md](access.md)).

From then on:

- the remedy is offered first: "Rihmasto has seen this before: last time ... fixed it";
- it is applied on its own only when it is **safe**: opening a view, reading again, an explanation, an
  investigation. Every use is counted, and one applied on its own is recorded as applied on its approver's word;
- a remedy that starts a job, sends a write again or changes code stays a proposal you confirm each time.

**What Rihmasto learned** on the Incidents page lists each remedy with:

- its uses;
- when it was last used;
- who approved it.

**Retire remedy** stops offering one.

## Investigate with Rihma

A Rihma agent investigates the incident in the agent channel, in the incident's own thread (`incident-i-0001`).
That thread belongs to the incident's project, or to the factory's own canon when no project is involved.

1. The agent reads the incident's masked context, its class and the remedies Rihmasto knows.
2. It answers by rule when no model is set up. Otherwise it answers through the analyst role: the cockpit's
   assistant model, the coding agent you already have, or a local model.
3. For a confidential project whose analyst role is hosted, nothing is sent: it answers by rule.

It posts its diagnosis with a **trace**: the basis, what it read, the records, the model, tokens and time. It
classifies the incident as one of:

- user setup;
- Rihmasto bug;
- project bug;
- external;
- unknown.

It proposes the next step: a remedy, a configuration change, or a fix.

## Fix and pull request

A fix is a test that reproduces the incident and the change, each a whole file. **Prepare the fix** takes it
the normal way:

- **Where it is made.** It works in a clone under the factory home, never in your own working tree, on its own
  branch `rihmasto/fix-i-0001`.
- **Fail-first.** The test is committed first and must fail; then the change is committed and the test must
  pass.
- **The suite.**
  - For a project's repository, the whole suite runs.
  - For Rihmasto's own repository, only the reproducing test runs here. The whole suite runs in CI on the pull
    request.
- **Protected paths.** A change to the contract, a `.gnomon/` surface or `.git` is refused.
- **The verifier.** An independent verifier reviews the change. Without one, the gate is not passed.

**Approve and open the pull request** needs four things:

- your approval;
- a persona that may approve (a developer, IT or a product owner; for Rihmasto's own repository only IT, the
  owner of this Rihmasto, or the solo person of a solo home);
- a gate that passed;
- a remote.

It pushes only the fix's branch, never a default branch. It opens the pull request with `gh` when it is
installed and signed in. Otherwise it gives you the branch and the exact commands. Rihmasto never merges: the
repository's own review decides.

## Feedback

**This is unclear / this is wrong** sits at the foot of every view and on each Ask Rihma answer. It records:

- the kind;
- where it is (the view and the words shown);
- your words;
- better words, if you have them.

Feedback about the same thing is grouped. Two notes, or one with better words, become a proposal of one of
these kinds:

- **a wording change:** the words in that view;
- **an assistant rule:** feedback on an Ask Rihma answer;
- **a prompt change:** feedback on an agent's answer.

A product owner, business owner, IT or developer approves it, with the final text. Approved changes are applied
from data files Rihmasto reads, never by editing code at run time:

- `heal/wording.json`: the cockpit replaces the words in that view;
- `heal/assistant_rules.json`: Ask Rihma reads the rules in its snapshot;
- `heal/prompt_rules.json`: every prompt a Rihma agent is given reads the approved rules through one hook
  (`kernel/prompt_rules.py`): the intake panel's perspectives, the spec, Ask Rihma, goal help and the agent
  channel's answers. With no approved rule a prompt is unchanged.

## Feeding a project

A folder scan that fails (an unreadable folder, a file name the system cannot decode) or runs past its time
gives a **partial map**:

- every file it could list, listed and not read;
- the folders it could not open, with the reason.

The person sees what was skipped and why. An incident is opened too. A failed adoption, intake or run is an
incident with its log tail, and **Run it again** starts the same job.

## Where it shows

- **The Incidents page** (`#/incidents`), and each project's **Incidents** tab: open, investigating, fixed and
  learned; What Rihmasto learned; Feedback.
- **What's next** on a project: an open incident with its Incidents view.
- **Home and Review:** a card while incidents are open.
- **Insights** (Health): incidents open, the median time to resolve, learned remedies used.
- **Ask Rihma:** it sees the open incidents and their remedies. It can propose to report what is wrong,
  investigate an incident, take a remedy, or give feedback, each checked like a click.
- **While the cockpit runs:** failed jobs, and failures the ledgers recorded (a check, an automation, a model
  endpoint, a refused runner), become incidents on the next sweep, once.
