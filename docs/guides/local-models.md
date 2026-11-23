# Running fully local

Rihma has no model family of its own (D-0005). Every role is a model and an endpoint in
[kernel/routing.json](../../kernel/routing.json), and every call goes through Gnomon. So the whole
factory can run on your own hardware: a GPU box on your network serving an OpenAI-compatible
endpoint, and no cloud at all.

## What you need

- **A GPU box** with an OpenAI-compatible server: llama.cpp's `llama-server`, vLLM, or any other
  server that answers `POST /v1/chat/completions`.
- **Two model families.** The verifier must be another family than the builder, and has no
  fallback. A local-only factory therefore serves at least two families: for example a Qwen
  model for the analyst and builder, and a GLM model for the verifier and the holdout author.
- **Gnomon** on the machine that runs the kernel and the cells. It is the only thing that talks
  to the GPU box.

## 1. Serve the models

Run one server per model, each on its own port. With llama.cpp, for example:

```bash
# on the GPU box
llama-server -m /models/builder-model.gguf  --host 0.0.0.0 --port 8080 -c 65536
llama-server -m /models/verifier-model.gguf --host 0.0.0.0 --port 8081 -c 65536
```

Any server that loads several models behind one URL works too; the `model` name in the routing
then picks one.

Keep these ports on your private network or VPN. They take requests with no key, so do not
publish them to the internet. If the server needs a key, give the endpoint an `api_key_env`.

## 2. Route the roles

The shipped [kernel/routing.json](../../kernel/routing.json) names no machine. Its `local`
endpoint is `http://127.0.0.1:8080/v1/chat/completions` (llama-server's default port on this
machine); it serves the assistant and the builder's fallback. The other roles use a cloud
endpoint whose key is read from `OPENCODE_API_KEY`.

Put your own routing in **`kernel/routing.local.json`**, beside the shipped file. It is
gitignored, so a GPU box's address never reaches a commit, and the kernel merges it over the
shipped file whenever it loads the routing:

- each role, model and endpoint it names replaces the shipped one whole (a role's `fallback`
  too: a role written without one has none);
- any other key it sets, such as `max_context_tokens`, replaces the shipped value;
- nothing is removed: a shipped endpoint no role uses is never compiled into a lane (`rihma
  doctor` still says whether its key variable is set, as a warning).

A small overlay that sends the assistant and the builder's fallback to a GPU box on your network:

```json
{
  "roles": {
    "builder":   {"model": "deepseek-v4-pro", "endpoint": "go",
                  "fallback": {"model": "qwen3.6-35b", "endpoint": "gpu"}},
    "assistant": {"model": "qwen3.6-35b", "endpoint": "gpu",
                  "fallback": {"model": "glm-5.3", "endpoint": "go"}}
  },
  "endpoints": {
    "gpu": {"kind": "openai", "url": "http://gpu-box.example:8080/v1/chat/completions"}
  }
}
```

The merged routing is checked like the shipped one, and `rihma doctor` says whether the overlay
is present (`routing_overlay`). A fully local factory overlays every role:

```json
{
  "max_context_tokens": 65536,
  "roles": {
    "analyst":        {"model": "qwen3-32b", "endpoint": "gpu-a"},
    "holdout_author": {"model": "glm-4.5-air", "endpoint": "gpu-b"},
    "builder":        {"model": "qwen3-32b", "endpoint": "gpu-a"},
    "verifier":       {"model": "glm-4.5-air", "endpoint": "gpu-b"},
    "assistant":      {"model": "qwen3-32b", "endpoint": "gpu-a"}
  },
  "models": {
    "qwen3-32b":   {"family": "qwen"},
    "glm-4.5-air": {"family": "glm"}
  },
  "endpoints": {
    "gpu-a": {"kind": "openai", "url": "http://gpu-box.example:8080/v1/chat/completions"},
    "gpu-b": {"kind": "openai", "url": "http://gpu-box.example:8081/v1/chat/completions"}
  }
}
```

- The kernel checks the routing whenever it loads it. `rihma lanes` loads it, so it is a quick
  check after an edit.
- **Context window.** Gnomon 0.6.6 asks the endpoint for its window (llama.cpp reports its
  `n_ctx`). To cap it, set `"max_context_tokens": 65536` on the endpoint itself. The top-level
  value is the fallback when the endpoint does not say.
- **Fallbacks.** A role can name a `fallback` on another local endpoint. The builder's fallback
  must not be the verifier's family, and the verifier has none.
- **Timeouts.** Lanes allow 300 s per request, for long local generations. A timeout is an
  apparatus failure, never a verdict on the work.

**The repository's own Gnomon surface.** `.gnomon/config.toml` is the surface this repository is
built under, not the lanes' routing. It names the same `local` endpoint at `127.0.0.1:8080`.
Gnomon reads that file as it is, with no overlay, and any byte changed in `.gnomon/` moves the
surface hash. If you build this repository with Gnomon against a server elsewhere, change the
`url` in your own checkout, and trust the new surface yourself (`gnomon trust`).

## 3. Count local spend

Add each local model to [kernel/prices.json](../../kernel/prices.json):

```json
"models": {
  "qwen3-32b":   {"local": true, "where": "the GPU box"},
  "glm-4.5-air": {"local": true, "where": "the GPU box"}
}
```

Local models cost no API money. Their tokens are reported as local spend, apart from cloud spend.
A model missing from the table is "not measured", never free.

## 4. Check it

```bash
rihma doctor                      # Gnomon, git, lanes; endpoints with a key variable say whether it is set
rihma lanes                       # checks the routing and compiles the analyst lane
```

Then start a project at the `explore` maturity ([Getting started](../getting-started.md#6-a-first-real-project)).
`rihma learn` and the cockpit's Floor report each builder model's record from the ledgers: cells
run, first-round pass rate, escalations and rounds to pass. That is the evidence to change the
routing on.

## Local and cloud together

You can mix: for example a local builder and a cloud verifier, or a local builder with a cloud
fallback for rate limits and outages. The rules are the same: the verifier is another family than
the builder and its fallback, and a key is read from the environment variable that `api_key_env`
names.
