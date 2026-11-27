---
id: D-0026
decided_by: owner
decided_on: 2026-11-25
kind: principle
status: proposed
amends: D-0023, D-0024
---

# Enforcement levels per environment: observe and advise by default, enforce only where the owner turns it on

The owner (2026-11-25), thinking aloud: "how do we make sure Rihmasto is aligned with the dev test prod split
if it's coming from GitHub or any pipeline ... in development we wouldn't want forced human check on
everything; in testing and production we wouldn't want any critical changes without human checks. So there
should be different levels of enforcement ... to what extent we can expect Rihmasto to govern such structure
or just take it as given ... stay true to the middle layer vision while helping to enforce the structure."

**The proposal.**

1. **Four levels.** For each environment and each check family Rihmasto applies one level:
   - **off**: Rihmasto does not look. The project's own pipeline still does what it does.
   - **advise**: a note in the project's record and a nudge in its view and in Ask Rihma. The work goes on.
     This is the default everywhere.
   - **require review**: a card for the named reviewer (a persona: the business owner, a product owner, a
     developer, IT, operations or compliance). The work goes on and the review is owed. Only that reviewer
     decides the card.
   - **enforce**: the work waits until the named reviewer decides the card. An approval is the override: it is
     recorded with its person and reason, and the same subject goes on from then. A refusal keeps it held.
2. **Three environments.** Development, testing and production. Rihmasto's own environments map onto them:
   preview and demo are development, staging is testing, production is production. A pipeline's
   environments map by their names (dev, development, local, preview: development; test, staging, qa, uat,
   acceptance: testing; prod, production, live: production).
3. **Four check families.**
   - **quality**: tests, the build pipeline's runs, health probes and the gate's verdict on a change.
   - **security**: open security findings, secrets and dependency audits.
   - **legal**: licences of what the product uses, and its bill of materials.
   - **governance**: a change itself entering the environment, approvals and the audits of how it was made.

   A family has a say when it has a finding. Governance has a say on every change that enters testing or
   production. In development it has a say only once its level there is above advise, so development stays
   free unless the owner turns it on.
4. **Two scopes, always shown.** The platform sets the levels every project starts from. A project may set its
   own level for any cell, and its own reviewer for any family. Every cell says where it comes from: this
   project, all projects, or Rihmasto's default. A project's cell can be given back to the platform.
5. **Two sources of truth, kept apart.**
   - **The project's own pipeline is taken as given.** Its GitHub environments (required reviewers, wait
     timers, which branches may deploy) and its default branch's protection (required reviews, required
     checks) are read with the person's own `gh` sign-in. Only GET requests are used, and nothing is ever
     written there. They are shown beside Rihmasto's levels, per environment, as one of:
     - **agree**: both ask for a person, or neither does;
     - **the pipeline is stricter**: the pipeline still holds the change. Rihmasto offers to take the
       pipeline's split as its own levels;
     - **Rihmasto is stricter**: Rihmasto says where in GitHub's settings a person could add required
       reviewers, and never adds them itself;
     - **nothing to compare**: it says why and how to fix it.
   - **Rihmasto's own checkpoints apply the levels.** These are its gate on a change of an attached repository
     (development), the deploy step of a release (each environment the release enters, after the security
     gate), and an automation that changes something (development unless the automation names its
     environment). The existing deploy gate card (IT, before production) and the security gate stay as they
     are; the levels add to them, never loosen them.
6. **Middle-layer rule.** By default Rihmasto observes and advises. It enforces only where a person turned it
   on, and it says so in words: what holds the work, which card, who decides, and that approving goes on.
   Nothing strands the person:
   - an unread pipeline says why and how to fix it;
   - an empty list says what would appear there and offers Ask Rihma why and how.
7. **Solo by default.** For one person, advise everywhere means nothing waits on them. Only what they set to
   enforce blocks work, and the solo person holds every reviewer persona. For a team, the named reviewer
   decides, and team mode's access rules apply.
8. **Governance and traceability.**
   - Every change of a level is signed by a named person in a persona that may set levels (business owner,
     IT, compliance, developer). It goes into the factory's ledger (platform) or the project's ledger.
   - Loosening a level needs a reason.
   - Every guard outcome (noted, review, held, cleared) is in the project's ledger, with the environment,
     family, level, subject and card. A cleared outcome carries its override.
   - A preview says what a change would do before anyone makes it: the cells, what happens next there, how
     the recorded outcomes would have differed, and which projects keep their own setting.
9. **UI and chat parity.** The levels are set in a project's Enforcement view (Govern capsule) and in Settings
   for all projects. Ask Rihma answers "how is production enforced here?" by rule. It proposes "require review
   in test" or "use the split" with the preview's lines, and the person confirms it, signed, through the same
   route.

**Presets.**

| Preset | Development | Testing | Production |
|---|---|---|---|
| Advise everywhere (default) | advise | advise | advise |
| The split (the owner's words) | advise | require review | enforce |
| Strict | require review | enforce | enforce |

**Open for the owner.**

- Whether "the split" should become the platform's default once a team works on a project.
- Whether a pipeline's required reviewers should count as Rihmasto's review, so a person is not asked twice.

Implemented as FR-ENF1: kernel/enforcement.py, kernel/enforcement_guard.py, kernel/enforcement_preview.py,
kernel/enforcement_pipeline.py, kernel/enforcement_chat.py, cockpit/enforcement_routes.py and
cockpit/static/enforcement.js.
