# Models setup

Rihmasto has no model of its own (D-0005): each of its roles is a model and an endpoint in the
routing. **Models setup** is where you see and set them, in the cockpit or on the command line
(FR-MDL1). For the file-level details behind it, see [Running fully local](local-models.md).

## The roles

| Role | What it does |
|---|---|
| Analyst | reads requests, asks the panel's questions, writes the spec, and talks with you in [Shape it in chat](shape-in-chat.md) |
| Holdout author | writes the hidden acceptance scenarios the builder never sees |
| Builder | writes the code and its tests in a cell |
| Verifier | checks the builder's work; it must be another model family than the builder |
| Assistant | answers Ask Rihma in the cockpit |

For each role the page shows its model and family, the endpoint's host, whether it is **local**
(this machine or a private network) or **hosted**, the name of the variable its key is read from
and whether a key is set (never the key), its fallback, and whether it answers: a local server is
checked on its port; a hosted endpoint with a key reads "Key set" until you test it.

**A key Gnomon holds counts.** Gnomon can keep keys of its own (`gnomon key set <endpoint>`, in its
credential store outside every repository: `%APPDATA%\gnomon\credentials.json` on Windows,
`~/.local/share/gnomon/credentials.json` elsewhere, or under `$XDG_DATA_HOME`), and uses one when the
variable is not set. Models setup asks `gnomon key list`, which prints names only, and shows such a key as
**key set by Gnomon**, not "no key". When Gnomon cannot say (it is not found, or the command fails) but its
store exists, the role reads **Gnomon may have its own key for this host**. Rihmasto never opens the store
and never reads a key's value, so **Test** cannot send a key Gnomon holds and says so; a run goes through
Gnomon and uses it. `rihmasto doctor` counts a key Gnomon holds as set too.

**No API key?** A role can be answered by the coding agent you already have: Claude Code (your
login), Codex or OpenCode, run headless with no tools in an empty folder. Models setup lists the ones
this machine has with their versions. **Use Claude Code (your login)**, **Use Codex** or **Use
OpenCode** answers every text role (or those you pick) with it, and `rihmasto models use claude-code`
does the same on the command line. Test sends its tiny prompt through the harness. It is slower than an
API endpoint and spends your own subscription. See
[Run Rihmasto with the coding agent you already have](harness-models.md).

## Open it

- **Settings > Models > Open Models setup**;
- **Home** shows a **Set up a model** card while no model Rihma talks with (the analyst or the
  assistant) answers, or Gnomon is not found;
- or ask Rihma: "Where do I put my API key?".

## Set a role

**Change** on a role opens a form:

- **Preset**: llama.cpp, Ollama or vLLM on this machine, OpenCode Go (the shipped hosted route),
  OpenAI, OpenRouter, or another OpenAI-compatible provider. A preset only fills the form.
- **Base URL**: the OpenAI-compatible base, such as `http://127.0.0.1:8080/v1`. Rihmasto calls
  `<base>/chat/completions`.
- **Model name**, as the endpoint knows it, and optionally its **family** (by default the name's
  leading letters: `qwen3:32b` is qwen).
- **The API key**: none (a local server), the **name** of an environment variable that holds it,
  or a key to **store**. A stored key is kept in `~/.rihmasto/secrets.json` (or the file
  `RIHMASTO_SECRETS_FILE` names), outside the repository, and handed to Gnomon in the variable
  `RIHMASTO_KEY_<ROLE>` when it runs. It is never shown again, never logged and never put in the
  ledger.
- **Keep the fallback**: a role that has one keeps it unless you untick it (`--no-fallback`). A local role
  that keeps a hosted fallback says so when you save it: a confidential project skips that fallback (it is
  never called, and the skip is in the project's ledger); untick it to drop it for every project.

**Save** writes the role to `kernel/routing.local.json`, this machine's overlay (gitignored, merged
over the shipped `kernel/routing.json`, which is never written). The merged routing is checked as the
kernel checks it: a change that would put the verifier in the builder's family is refused, and
nothing is written. The factory's ledger records `models_set`: who set which role, to which model and
host, and whether the key comes from the environment, is stored or is none.

**Test** sends the role's endpoint a tiny prompt with its key, and says how fast it answered and
what it said, or the error (a refused key, nothing answering, a key that is not set). It records
nothing. It is the one place Rihmasto calls an endpoint itself; every real model call goes through
Gnomon.

**Back to shipped** removes the role from the overlay, with an endpoint and a stored key only it used
(`models_removed` in the ledger).

The next message in Shape it in chat uses the new routing at once; the analyst lane is compiled again
from the routing before each answer.

## On the command line

```bash
rihmasto models list [--no-probe]       # each role, as the page shows it
rihmasto models presets
rihmasto models test analyst
rihmasto models set analyst --base-url http://127.0.0.1:8080/v1 --model qwen3:32b \
    --person "Ilkka Example" --persona it
rihmasto models set builder --base-url https://openrouter.ai/api/v1 --model qwen/qwen3-32b \
    --key-env OPENROUTER_API_KEY --person "Ilkka Example" --persona it
rihmasto models set analyst --base-url https://api.example.com/v1 --model some-model \
    --key-stdin --person "Ilkka Example" --persona it < key.txt
rihmasto models remove analyst --person "Ilkka Example" --persona it
rihmasto models use claude-code [--roles all|analyst,assistant] --person "Ilkka Example" --persona it
```

`--key-stdin` reads the key from standard input, so it never appears in your shell's history or the
process list. Nothing the command prints holds the key.

## The API

| Method and path | What it does |
|---|---|
| `GET /api/models` | the roles, the presets, whether Gnomon is found, `ready` (a model Rihma talks with answers), the overlay's path and where stored keys are kept |
| `PUT /api/models/<role>` | `{base_url, model, family?, key_env? or key?, keep_fallback?, person, persona}`; a refused change is a 400 and writes nothing |
| `POST /api/models/<role>/test` | `{person, persona}`: the tiny prompt; records nothing |
| `POST /api/models/<role>/remove` | `{person, persona}`: back to the shipped routing |
| `POST /api/models/use` | `{harness, roles?, model?, family?, private?, command?, person, persona}`: the text roles (or those named) answered by a coding agent on this machine ([harness-models.md](harness-models.md)); `GET /api/models` lists the harnesses found and their versions |
