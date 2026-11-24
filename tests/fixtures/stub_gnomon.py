"""A stand-in for the `gnomon` command, for tests that need a real Gnomon process without Gnomon.

    stub_gnomon.py task --task-file F --role R --json --yes ...
        reads the lane's compiled surface (.gnomon/roles.toml and .gnomon/config.toml in the working folder),
        sends the task to the role's endpoint as an OpenAI-compatible chat request, and when that fails, to the
        role's fallback, as Gnomon does; prints one JSON record. A host named in $STUB_GNOMON_HOSTS (a JSON
        object, host to "127.0.0.1:port") is reached at that address, so a "hosted" endpoint is a stub on this
        machine and nothing leaves it.
    stub_gnomon.py key list
        prints the variable names in $STUB_GNOMON_KEYS (comma separated) as `gnomon key list` does: names only.
"""

import json
import os
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _url(url: str) -> str:
    hosts = json.loads(os.environ.get("STUB_GNOMON_HOSTS") or "{}")
    parts = urllib.parse.urlsplit(url)
    if parts.hostname in hosts:
        parts = parts._replace(scheme="http", netloc=hosts[parts.hostname])
    return urllib.parse.urlunsplit(parts)


def _send(url: str, model: str, prompt: str) -> str:
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    req = urllib.request.Request(_url(url), data=body, headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=10) as res:
        data = json.loads(res.read().decode("utf-8"))
    return str(data["choices"][0]["message"]["content"])


def task(args: list[str]) -> int:
    prompt = Path(args[args.index("--task-file") + 1]).read_text(encoding="utf-8")
    role = args[args.index("--role") + 1]
    surface = Path.cwd() / ".gnomon"
    roles = tomllib.loads((surface / "roles.toml").read_text(encoding="utf-8"))["roles"]
    endpoints = tomllib.loads((surface / "config.toml").read_text(encoding="utf-8"))["endpoints"]
    spec = roles[role]
    tried = []
    for route in (spec, spec.get("fallback")):
        if not route:
            continue
        tried.append(route["endpoint"])
        try:
            out = _send(endpoints[route["endpoint"]]["url"], route["model"], prompt)
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            continue
        print(json.dumps({"output": out, "bucket": "completed", "stop_reason": "done", "endpoints": tried}))
        return 0
    print(json.dumps({"output": "", "bucket": "apparatus_failure", "stop_reason": f"no endpoint answered: {tried}"}))
    return 1


def main(args: list[str]) -> int:
    if args[:2] == ["key", "list"]:
        print("Credentials in (a stub)\n(names only — values are never printed)\n")
        for name in [n for n in (os.environ.get("STUB_GNOMON_KEYS") or "").split(",") if n]:
            print(f"  {name}")
        print("\n  gnomon key set <endpoint|VARIABLE>")
        return 0
    if args[:1] == ["task"]:
        return task(args)
    print(f"stub gnomon: {args!r} is not stubbed", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
