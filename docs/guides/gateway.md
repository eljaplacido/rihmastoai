# The capability gateway

The gateway is one OpenAI-compatible endpoint for the capabilities a site runs. A client asks for a
**workload**, such as `classify` or `dev-assistant`, in the request's `model` field, and never for a
model. The site decides which model serves each workload and what happens when that model is down.
Models can change underneath without any client changing.

For each workload the gateway has:

- a declared **fallback ladder** (L1 to L4), filtered by the site mode and the request's data class;
- **quotas**, so batch work cannot starve interactive work;
- an **audit**: one hash-chained record per request, with no prompt or answer in it.

The code is in [gateway/](../../gateway/). It uses the standard library only, like the rest of Rihma.

## Start it

From the repository root:

```bash
python -m gateway.server --config gateway.json            # listens on 127.0.0.1:8792
```

It prints the address, the site mode, the workloads and where the audit is. Point any
OpenAI-compatible client at `http://127.0.0.1:8792/v1` and use a workload name as the model:

```bash
curl -s http://127.0.0.1:8792/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model": "classify", "messages": [{"role": "user", "content": "Invoice or receipt? ..."}]}'
curl -s http://127.0.0.1:8792/v1/models                   # the workloads, never the models
```

| Path | What it does |
|---|---|
| `POST /v1/chat/completions` | Serves one request for the workload named in `model`. |
| `GET /v1/models` | Lists the workloads with their class, data class and ladder levels. The models behind them are not listed. |
| `GET /v1/deferred/<id>` | Returns the outcome of a request queued at L4. |
| `GET /health` | Returns the site mode, the requests in flight per class against their limits, and the queue length. |

The gateway listens on loopback only. To serve other machines, put it behind your TLS reverse proxy
and start it with `--host <address> --behind-proxy`; without that flag a non-loopback address is
refused. The gateway has no client authentication of its own. On loopback only local processes can
reach it. Behind a proxy, the proxy authenticates the clients.

## The configuration

One JSON file. The gateway checks all of it at start. A mistake is refused with the path of the
wrong value (for example `workloads.classify.ladder.L3[0].upstream: expected a cloud upstream at L3`),
so the gateway never runs on a config it only half understands.

```json
{
  "format": "rihma.gateway.v1",
  "site": {"mode": "connected", "cloud_max_data_class": "public"},
  "upstreams": {
    "gpu-a":  {"url": "http://gpu-a.lan:8080/v1"},
    "gpu-b":  {"url": "http://gpu-b.lan:8080/v1"},
    "small":  {"url": "http://gpu-b.lan:8081/v1", "timeout_s": 30},
    "cloud":  {"url": "https://api.provider.example/v1", "cloud": true, "api_key_env": "PROVIDER_API_KEY"}
  },
  "workloads": {
    "dev-assistant": {
      "class": "interactive", "data_class": "internal", "description": "coding help in the editor",
      "ladder": {
        "L1": [{"upstream": "gpu-a", "model": "qwen3-32b"}, {"upstream": "gpu-b", "model": "qwen3-32b"}],
        "L2": [{"upstream": "small", "model": "qwen3-8b"}],
        "L3": [{"upstream": "cloud", "model": "provider-large"}]
      }
    },
    "classify": {
      "class": "batch", "data_class": "public", "rate": {"per_minute": 120, "burst": 20},
      "ladder": {"L1": [{"upstream": "gpu-b", "model": "qwen3-8b"}], "L4": "defer"}
    }
  },
  "quotas": {"concurrency": {"interactive": 8, "batch": 2, "specialist": 2}, "wait_s": 0},
  "audit": {"path": "audit/gateway.jsonl", "content_capture": false},
  "defer": {"max_queue": 100, "retry_s": 30, "max_attempts": 5}
}
```

### Upstreams

An upstream is any OpenAI-compatible server: llama.cpp's `llama-server`, vLLM, or a cloud API. Give
its base URL (`.../v1`) or the full `.../v1/chat/completions` URL.

- `cloud`: set it to `true` for every upstream that is not on your own network. The site mode
  filters on this flag, so a cloud API declared without it would be treated as local. A cloud
  upstream must use https.
- `api_key_env`: the **name** of the environment variable that holds the key. The gateway reads it
  when it calls the upstream and sends it as a bearer token. A config that contains a key itself
  (`api_key`, `token`, `secret` and the like) is refused. The key never appears in the audit, an
  error or a log line. The gateway does not follow redirects, so a key is never sent to a host that
  the config does not name.
- `timeout_s`: how long one call may take (60 s by default). A timeout fails that rung of the
  ladder, and the gateway tries the next.

### Workloads and the fallback ladder

A workload has a `class` (`interactive`, `batch` or `specialist`), a `data_class` floor, an optional
`rate`, and a `ladder`. The gateway tries the targets in order, and the first valid answer wins:

| Level | What it is | What the client sees |
|---|---|---|
| **L1** | The workload's own model. List several upstreams to fall back to the same workload on another one. | A normal answer. |
| **L2** | A smaller model. | An answer flagged **degraded**: the header `X-Gateway-Degraded: true`, and `"degraded": true` with a `degraded_reason` in the answer's `gateway` field. |
| **L3** | A cloud upstream. Used only when the site mode and the request's data class allow it. | A normal answer, with `"level": "L3"`. |
| **L4** | `"defer"`: the request is queued. | `202` with `"status": "queued"`, `"answer": null` and a message starting "no answer yet". |

A rung fails when its upstream cannot be reached, times out, answers with a status other than 2xx,
or returns something that is not a chat completion with at least one choice. Every answer has the
headers `X-Gateway-Workload`, `X-Gateway-Level`, `X-Gateway-Degraded` and `X-Gateway-Request-Id`, and
a `gateway` field in the body with the workload, the level, the upstream and the model that
answered. A target can also set `"degraded": true` on L1 or L3, for example for a smaller cloud model.

When no rung answers and the ladder has no L4, the reply is `503` and lists each attempt and each
target that was skipped, with the reason. It never contains an upstream's body.

### Site mode and data classes

Data classes, from least to most sensitive: `public`, `internal`, `confidential`, `restricted`.

- `"mode": "air-gapped"` (the default when `site` is missing): the gateway never calls a cloud
  upstream, whatever the ladder says.
- `"mode": "connected"`: the gateway calls a cloud upstream only for requests whose data class is at
  most `cloud_max_data_class` (`public` by default).

A request's data class is the workload's `data_class`, or higher if the request asks for a higher one,
in `"data_class"` in the body or in the `X-Data-Class` header. A request can only raise the class,
never lower it below the workload's own. The gateway strips `data_class` from the body before it
calls an upstream.

### Quotas

- **Concurrency per class.** Each class has its own limit on requests in flight
  (`quotas.concurrency`; the defaults are interactive 8, batch 2, specialist 2). When batch reaches
  its limit, a new batch request gets `429` with `Retry-After`, or it waits up to `quotas.wait_s`
  seconds for a free slot. Interactive requests keep their own slots. Set the batch limit below what
  your upstreams can serve, so that batch work never takes all the capacity.
- **A token bucket per workload.** A workload's `rate` holds it to `per_minute` requests, with
  bursts up to `burst`. An empty bucket gives `429` with a `Retry-After` of the seconds until the next
  token. The bucket counts requests, not model tokens.

Both live in memory and are per gateway process.

### L4: deferred requests

A queued request is retried every `defer.retry_s` seconds, up to `defer.max_attempts` times, within
its class's concurrency limit. The client asks `GET /v1/deferred/<id>` (the `Location` header of the
202) and gets one of three replies:

- `202` with "no answer yet", while the request is still queued;
- `200` with the answer and its level, once only;
- `503` when the gateway gave up after the last attempt.

The queue is kept in memory only. To retry a request the queue must keep its prompt, and writing the
queue to disk would store that content. A restart therefore forgets queued requests. The audit still
holds a record of each one.

## The audit

Every request gets one record, whatever its outcome: answered, deferred, failed, or refused (unknown
workload, bad request, unreadable body, quota). The audit is a JSONL file with the kernel's ledger
format: `seq`, `event`, `prev` and `hash`, hashed with `kernel.ledger`. The kernel's ledger check
verifies it, and so does:

```bash
python -m gateway.server --config gateway.json --verify-audit     # exit 0 when the chain is intact
```

Each event is `{"kind": "gateway_request", "at": ..., "payload": ...}`. The payload holds:

- the request id, the workload and its class, and the data class;
- the status (`answered`, `deferred`, `failed` or `refused`) and the reason for a refusal;
- the level that answered and whether the answer was degraded;
- the upstream and the model, and the HTTP status;
- the latency, and the token counts when the upstream returned them;
- each attempt (level, upstream, model, outcome and milliseconds), and each target skipped with the
  reason;
- the deferred id, for a request queued at L4.

The payload **never** holds the prompt or the answer, unless the config sets
`"audit": {"content_capture": true}`. With that setting, the messages and the answer's choices are
recorded too. Turn it on only where your data rules allow the audit to hold that content.

## How it relates to capability packs

A [capability pack](packs-and-evidence.md) pins what a release is: pack version equals behaviour
version. When a pack declares the workloads its product calls at run time, each one becomes a
gateway workload:

```json
"runtime": {"declared": true, "workloads": [
  {"name": "classify", "class": "batch", "data_class": "internal", "model": "qwen3-8b"}
]}
```

The workload's name, class and data class come from the pack. Its L1 is the model the pack was
accepted with. The site adds the upstream and the rest of the ladder (L2 to L4), which depend on the
site and not on the release. From Python, at the repository root:

```python
from gateway.packs import workloads_from_pack
entries = workloads_from_pack(pack, upstream="gpu-b")   # paste into the config's "workloads"
```

To see where a running config no longer matches a pack, run:

```bash
python -m gateway.server --config gateway.json --check-pack capability-pack.json
```

It reports a workload the pack declares but the gateway lacks, a different class, or an L1 serving
another model than the one the pack was accepted with. The command exits 1 when anything drifted.
Swapping a workload's L1 model is a behaviour change. Make it through the change loop, which
re-measures the capability and gives the pack a new version, not by editing the gateway config
alone. The L2 and L3 fallbacks are where the gateway may serve something other than the accepted
model, and the gateway says so in every answer through its level and degraded flag.

See [the capability layer](../capability-layer.md) for packs, profiles and the change loop, and
[running fully local](local-models.md) for serving models on your own hardware.

## Not built yet

- **Packs do not declare runtime workloads yet.** [kernel/packs.py](../../kernel/packs.py) writes
  `"runtime": {"declared": false}`, so `workloads_from_pack` returns nothing for today's packs. The
  gateway reads the shape shown above when a pack provides it.
- **Streaming.** A request with `"stream": true` is refused with `400`. Send `"stream": false`.
- **No `rihma-gateway` command.** The gateway runs as `python -m gateway.server` from a checkout.
  `pip install -e .` does not install a command for it yet.
- **Client authentication.** There is none of its own: use loopback, or a proxy that authenticates.
- **Persistent queue.** Deferred requests live in memory, as explained above.
- **Quotas across processes.** Limits and buckets are per process. Two gateways sharing upstreams
  each enforce their own limits. Give each gateway its own audit file.
