# Machines, asks between agents, and Test connection

Work rarely happens on one computer. A coding agent runs in a terminal on your laptop, another on a build server, a
working copy sits on a third machine, and when something there needs doing, the usual way is to copy a message, paste
it into the other agent, wait, and copy its answer back. Rihmasto carries that back-and-forth for you: you put the
question to the agent where it runs, Rihmasto delivers it the best way that machine allows, and the answer comes back
into the project's agent channel, beside everything else about the project (FR-XAG1). Wherever something Rihmasto
needs is not reachable, **Test connection** says why, how to fix it on that system, and drafts the ask to the agent
there (FR-RCH1).

## Machines

**Settings › Machines** lists the computers your agents and working copies are on. The list is shared by all
projects. Each machine has:

- a **name** (`laptop`, `build-server`);
- **how it is reached**: `ssh` (an alias your ssh knows, or `user@host`), `https` (an address in front of a
  cockpit or an agent), or **by hand** (nothing connects; asks go by copy and paste);
- its **system** (Windows, Linux or macOS), so a fix is given for that system;
- the **agents** that run there (`claude-code`, `codex`), which asks name.

Working alone you keep the list as a developer; in a team, IT keeps it. Every change is signed and recorded in
Rihmasto's own ledger with the machine's name and what changed, never its address.

```
rihmasto machines add laptop --reach ssh --address me@laptop --os windows --agent claude-code \
    --person "Dana Example" --persona developer
rihmasto machines list
rihmasto machines remove laptop --person "Dana Example" --persona developer
```

Ask Rihma: "which machines do I have?", "add the machine build-server, reached by ssh me@build-server, linux",
"remove the machine laptop" (each a proposal you confirm).

## Asks to agents

A project's **Agent channel** has **Asks to agents**. An ask is a question to a named agent, optionally on a named
machine, with why you ask and the answer you expect. It is posted in the channel addressed to that agent, signed with
your name, and its state follows it: **waiting**, **delivered**, **answered**, **expired** (after 7 days unless you
set another, at most 30) or **withdrawn**. It reaches the agent one of three ways, and all of them end in the same
thread:

1. **An agent on this machine** reads it over MCP: `rihma_channel_read` lists it under `asked_agents`, and the
   session-start section (`rihmasto ide <project> --section`) shows it under "Questions for you". The agent answers
   with `rihma_channel_post`, `reply_to` the question's id.
2. **An agent on another machine** answers through a **Reply link**: shown once, kept only as its hash, it expires
   (24 hours unless you set another, at most 7 days) and takes one answer. The agent calls two JSON endpoints:

   ```
   curl -s -X POST <cockpit>/x/api/ask    -H 'Content-Type: application/json' -d '{"token": "<token>"}'
   curl -s -X POST <cockpit>/x/api/answer -H 'Content-Type: application/json' \
        -d '{"token": "<token>", "answer": "<the answer>"}'
   ```

   The cockpit listens on this computer only. A reply link reaches it from elsewhere only through the cockpit's one
   trusted https front (`python -m cockpit.server --public-origin https://…`, for example `tailscale serve` or a
   company reverse proxy); without one, the link says it works on this computer only. A wrong, used or expired
   token, a call without a JSON body or from another site is refused, and refused tries are slowed per address.
3. **Always: Copy for the other agent** gives one self-contained message (what to do, why, the answer expected, how
   to answer, the ask's id) to paste into the other agent, and **Paste the answer** files what came back as that
   agent's reply, vouched for by you.

Home's **Waiting on other agents** lists every ask still waiting, oldest first. Ask Rihma answers "what am I waiting on
from other agents?", proposes "ask the agent on laptop to run the tests and tell me what fails", files "the answer to
AK-0002 is …" and withdraws "withdraw AK-0002"; you confirm each, signed.

```
rihmasto asks put <project> --to claude-code --machine laptop --text "Run git status and say the branch" \
    --person "Dana Example" --persona developer
rihmasto asks copy <project> AK-0001 --person ... --persona ...      # the message for the other agent
rihmasto asks answer <project> AK-0001 --text "main, clean" --person ... --persona ...
rihmasto asks link <project> AK-0001 --base https://cockpit.example --person ... --persona ...
rihmasto asks withdraw <project> AK-0001 --person ... --persona ...
rihmasto asks list [--project <project>]
```

The ledger records each ask's id, whom it is to, how it was delivered and who answered, never the words.

## Test connection

Test connection is on each machine in Settings, on a project's **Work in progress** when its working copy cannot be
read here, and as `rihmasto reach <machine|project|https://…|github>`. It tests once and records nothing:

- a machine reached by ssh: `ssh -v -o BatchMode=yes -o ConnectTimeout=… <address> exit`. Batch mode never asks for a
  password, a host key is never accepted for you, and nothing runs on the other side;
- an https address: one GET; GitHub: `gh auth status`; a project: whether its working copy is here and is git.

The verdict says the specific reason: the name does not resolve, no route, refused (nothing listens: no SSH server),
timed out (off, asleep, or a firewall), an unknown host key, the key refused for that user, or the session dropped
after the key was accepted (on Windows, a directory account that gets no session from a key alone). The fix is
given as steps for the machine's system: installing and starting the SSH server, where this machine's public key
goes and the file's permissions (only the public key is read, from `~/.ssh/*.pub`), a local account where a directory
account fails, checking a host key's fingerprint by hand.

When a machine is not reachable, Rihma drafts the ask to its agent with the same steps; **Send to the agent on …**
puts it in the project you pick, and with nothing connected there you copy it over. Nothing is sent without your
Confirm. Ask Rihma: "is the laptop reachable?", "test the connection to build-server", "can you reach github?".
