"""Infrastructure checks of what a service depends on (FR-ITO1 with FR-CHK1): its database, integrations and jobs.

- **database**: a declared database binding (``binding``, else the project's first database integration; or an
  ``endpoint`` given) connects and answers within ``max_ms`` (500). A SQLite file opens read-only and answers
  ``SELECT 1``, and its size is compared with the last run (``growth_pct``, 50). PostgreSQL and MySQL answer their
  own protocol's first round trip with no credential (PostgreSQL's SSL request, MySQL's greeting with its version):
  Rihmasto holds no database driver and signs in nowhere, so a query and the storage size there are not measured
  and said so. The reference connector of the kind (kernel/connectors.py) is named; it is never called from here.
  A backup location (``backup_dir``) has its newest file's age checked against ``backup_max_hours`` (26);
- **integration**: each declared integration bound to an endpoint answers (an HTTP endpoint any status under 500:
  a 401 says it is there and wants its credential, which is never sent; any other endpoint a TCP connection);
  credential expiry from IT's rotation reminders (kernel/itdata_actions.py) and the dates given in ``expires``
  (``ORDERS_API_TOKEN=2026-12-31``); quota headroom when the endpoint reports it (``X-RateLimit-Remaining`` of
  ``X-RateLimit-Limit``) against ``quota_min_pct`` (10);
- **job**: the project's scheduled work: each scheduled automation's last run against its schedule and its failures
  in a row, the duration trend of its scheduled checks, and how fresh its output is (``output``, a file or folder,
  against ``max_age_hours``, 26).

Each one says "not measured" with why when the project has nothing of its kind.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import statistics
import struct
import time
import urllib.error
from pathlib import Path
from typing import Any

from kernel.checks import Check, Ctx, infra, infra_settings, not_measured, result
from kernel.checks import infra_targets as tg

DB_FAMILIES = ("database",)
SSL_REQUEST = struct.pack("!ii", 8, 80877103)
PG_WAIT = 0.25            # seconds a PostgreSQL server stays quiet before and after its one-byte answer
CONNECT_MIN = 3.0         # seconds: longer than Windows takes to report a refused loopback port (about 2 s)


def _now(ctx: Ctx) -> dt.datetime:
    return ctx.project.factory.clock.now()


def _age_hours(ctx: Ctx, mtime: float) -> float:
    return (_now(ctx) - dt.datetime.fromtimestamp(mtime, dt.UTC)).total_seconds() / 3600


# -- database ---------------------------------------------------------------------------------------------------

def _db_target(ctx: Ctx) -> dict[str, Any] | None:
    endpoint = str(ctx.config.get("endpoint") or "").strip()
    if endpoint:
        return {"name": "given", "kind": endpoint.split(":", 1)[0], "endpoint": endpoint, "environment": "",
                "connector": None}
    wanted, env = str(ctx.config.get("binding") or ""), str(ctx.config.get("environment") or "") or None
    for b in tg.bindings(ctx.project):
        if (wanted and b["name"] != wanted) or (not wanted and b["family"] not in DB_FAMILIES):
            continue
        url, where = tg.endpoint_of(b, env)
        return {"name": b["name"], "kind": b["kind"], "endpoint": url, "environment": where,
                "connector": b.get("connector")}
    return None


def _sqlite(path: Path, budget: int) -> dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "why": f"the SQLite file {path.name} is not there"}
    started = time.monotonic()
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=budget / 1000)
    try:
        con.execute("SELECT 1").fetchone()
    finally:
        con.close()
    ms = round((time.monotonic() - started) * 1000)
    size = path.stat().st_size + sum(p.stat().st_size for p in (Path(str(path) + "-wal"),) if p.is_file())
    return {"ok": True, "ms": ms, "bytes": size, "said": f"opened read-only and answered SELECT 1 in {ms} ms"}


def _quiet(sock: Any, wait: float) -> bytes:
    """What the server says by itself within ``wait`` seconds (nothing, from a PostgreSQL server)."""
    before = sock.gettimeout()
    sock.settimeout(wait)
    try:
        return bytes(sock.recv(64))
    except (TimeoutError, BlockingIOError):
        return b""
    finally:
        sock.settimeout(before)


def _postgres(sock: Any) -> tuple[bytes | None, float]:
    """PostgreSQL's answer to its SSL request: one byte, S or N, then nothing until the client speaks again; any other
    server (an SSH banner, a reply in words) is None. With the round trip's own seconds, never the quiet waits'."""
    if _quiet(sock, PG_WAIT):                     # PostgreSQL never speaks first: an SSH or SMTP server does
        return None, 0.0
    asked = time.monotonic()
    sock.sendall(SSL_REQUEST)
    reply = bytes(sock.recv(64))
    took = time.monotonic() - asked
    if len(reply) != 1 or reply not in (b"S", b"N") or _quiet(sock, PG_WAIT):
        return None, took
    return reply, took


def _handshake(kind: str, host: str, port: int, budget: int) -> dict[str, Any]:
    started = time.monotonic()
    with infra.connect((host, port), timeout=max(CONNECT_MIN, budget / 1000 * 4)) as sock:
        if kind in ("postgres", "postgresql"):
            connected = time.monotonic()
            reply, took = _postgres(sock)
            if reply is None:
                return {"ok": False, "why": f"{host}:{port} answered, but not as PostgreSQL does (the wrong port, "
                                            "or another server there)"}
            said = "PostgreSQL answered its SSL request (" + ("TLS offered" if reply == b"S" else "no TLS") + ")"
            version = None
            started = time.monotonic() - (connected - started) - took     # connecting and the round trip only
        elif kind == "mysql":
            head = sock.recv(256)
            if len(head) < 6 or head[4] != 10:
                return {"ok": False, "why": f"{host}:{port} answered, but not with a MySQL greeting"}
            version = head[5:].split(b"\0", 1)[0].decode("ascii", "replace")[:40]
            said, reply = f"MySQL greeted with version {version}", None
        else:
            said, version = "the port answers", None
    ms = round((time.monotonic() - started) * 1000)
    return {"ok": True, "ms": ms, "said": f"{said} in {ms} ms", "version": version}


def _backup(ctx: Ctx) -> tuple[str | None, str]:
    """(a problem or None, the evidence line) for the backup location."""
    where = str(ctx.config.get("backup_dir") or "").strip()
    if not where:
        return None, "backup recency: not measured (no backup location declared: give this check backup_dir)"
    folder, limit = Path(where), infra.number(ctx, "backup_max_hours", 26)
    files = [p for p in folder.glob("*") if p.is_file()] + [p for p in folder.glob("*/*") if p.is_file()] \
        if folder.is_dir() else []
    if not files:
        return f"no backup found in {folder.name}", f"backup recency: no file in {where}"
    newest = max(files, key=lambda p: p.stat().st_mtime)
    hours = _age_hours(ctx, newest.stat().st_mtime)
    line = f"backup recency: the newest, {newest.name}, is {hours:.1f} hours old (at most {limit})"
    return (f"the newest backup is {hours:.0f} hours old (over {limit})" if hours > limit else None), line


def _before(ctx: Ctx, target: str) -> dict[str, Any] | None:
    from kernel.checks import store as cstore

    rows = [r for r in cstore.results(ctx.project, None, 200) if r.get("kind") == "database"
            and r.get("target") == target and r.get("bytes") is not None]
    return rows[-1] if rows else None


def _probe(t: dict[str, Any], kind: str, budget: int) -> dict[str, Any]:
    """The database's first round trip: a SQLite file opened read-only, else its protocol's greeting."""
    try:
        if kind == "sqlite" or t["endpoint"].startswith("sqlite:"):
            return _sqlite(Path(t["endpoint"].removeprefix("sqlite:///")), budget)
        hp = tg.host_port(t["endpoint"])
        if hp is None:
            return {"ok": False, "why": "its endpoint names no host"}
        return _handshake(kind, hp[0], hp[1], budget)
    except ConnectionRefusedError:
        return {"ok": False, "why": "nothing listens on its port: the connection was refused (is the server running, "
                                    "on this port?)"}
    except TimeoutError as exc:
        return {"ok": False, "why": f"no answer in time ({exc or 'timed out'}): a firewall drops the connection, or "
                                    "the host is down"}
    except (OSError, sqlite3.Error) as exc:
        return {"ok": False, "why": f"it could not be reached ({type(exc).__name__}: {exc})"}


def _storage(ctx: Ctx, name: str, size: int | None) -> tuple[str, str | None]:
    """The storage line, and a problem when it grew past ``growth_pct`` since the last run."""
    if size is None:
        return "query and storage size: not measured (Rihmasto signs in to no database server)", None
    before, limit = _before(ctx, name), infra.number(ctx, "growth_pct", 50)
    if not (before and before["bytes"]):
        return f"storage: {size} bytes (growth is measured from the next run)", None
    grew = (size - before["bytes"]) * 100 / before["bytes"]
    line = f"storage: {size} bytes, {grew:+.0f}% since the last run (at most {limit}%)"
    return line, (f"storage grew {grew:.0f}% since the last run (over {limit}%)" if grew > limit else None)


def database(ctx: Ctx) -> dict[str, Any]:
    t = _db_target(ctx)
    if t is None:
        return not_measured("no database to check: the project declares no database integration (declare one in "
                            "the Plan's Data integrations, or give this check an endpoint)")
    if not t["endpoint"]:
        return not_measured(f"{t['name']} is declared but not bound to an endpoint yet: IT binds it on a paved road")
    budget, kind = infra.number(ctx, "max_ms", 500), t["kind"].lower()
    lines = [f"{t['name']} ({kind}" + (f", {t['environment']}" if t["environment"] else "") + ")"]
    if t.get("connector"):
        lines.append(f"its reference connector is {t['connector']}: named, not called from a check")
    data: dict[str, Any] = {"target": t["name"], "database": kind}
    got = _probe(t, kind, budget)
    if not got["ok"]:
        return result("failed", f"{t['name']}: {got['why']}", lines + [got["why"]], remedy="database", **data)
    data.update(ms=got["ms"], version=got.get("version"), **({"bytes": got["bytes"]} if "bytes" in got else {}))
    storage, grew = _storage(ctx, t["name"], got.get("bytes"))
    trouble, backup = _backup(ctx)
    lines += [got["said"], storage, backup]
    problems = [f"{got['ms']} ms, over the {budget} ms budget"] if got["ms"] > budget else []
    problems += [p for p in (grew, trouble) if p]
    if problems:
        return result("failed", f"{t['name']}: " + "; ".join(problems), lines,
                      remedy="backup" if trouble else "database", **data)
    return result("passed", f"{t['name']} answered in {got['ms']} ms", lines, **data)


# -- integrations ----------------------------------------------------------------------------------------------

def _expiries(ctx: Ctx) -> dict[str, str]:
    from kernel import itdata as it

    out = {name: str(e.get("due")) for name, e in it.kept(ctx.project.factory, "rotation.json").items()
           if isinstance(e, dict) and e.get("due")}
    for pair in tg.as_list(ctx.config.get("expires")):
        name, _, day = pair.partition("=")
        if name.strip() and day.strip():
            out[name.strip()] = day.strip()
    return out


def _credential_lines(ctx: Ctx, names: list[str], dates: dict[str, str]) -> tuple[list[str], list[str]]:
    today, problems, lines = _now(ctx).date(), [], []
    for name in names:
        if name not in dates:
            lines.append(f"{name}: no expiry date declared")
            continue
        try:
            left = (dt.date.fromisoformat(dates[name]) - today).days
        except ValueError:
            lines.append(f"{name}: the expiry {dates[name]!r} is not a date")
            continue
        lines.append(f"{name}: expires or is due for rotation on {dates[name]} ({left} days)")
        if left < 0:
            problems.append(f"{name} expired {-left} days ago")
        elif left < 14:
            problems.append(f"{name} expires in {left} days")
    return problems, lines


def _quota(heads: dict[str, str], host: str, quota_min: int) -> tuple[str | None, str, float | None]:
    """The quota headroom an endpoint reports (X-RateLimit-Remaining of X-RateLimit-Limit), and a problem."""
    left, limit = str(heads.get("x-ratelimit-remaining") or ""), str(heads.get("x-ratelimit-limit") or "")
    if not (left.isdigit() and limit.isdigit() and int(limit)):
        return None, "; quota headroom: not reported by the endpoint", None
    pct = int(left) * 100 / int(limit)
    problem = f"{host} has {pct:.0f}% of its quota left (under {quota_min}%)" if pct < quota_min else None
    return problem, f"; quota headroom {left} of {limit} ({pct:.0f}%)", round(pct, 1)


def _http_health(url: str, host: str, quota_min: int) -> tuple[str | None, str, dict[str, Any]]:
    try:
        got = infra.fetch(url, timeout=10)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        why = getattr(exc, "reason", exc)
        return f"{host} could not be reached ({why})", f"GET {url}: {why}", {}
    measured: dict[str, Any] = {"status": got["status"], "ms": round(got["ms"])}
    low, said, pct = _quota({k.lower(): v for k, v in got["headers"].items()}, host, quota_min)
    if pct is not None:
        measured["quota_pct"] = pct
    problem = f"{host} answered {got['status']}" if got["status"] >= 500 else low
    return problem, f"GET {url}: {got['status']} in {got['ms']:.0f} ms (no credential sent){said}", measured


def _endpoint_health(url: str, quota_min: int) -> tuple[str | None, str, dict[str, Any]]:
    """(a problem or None, the evidence line, what was measured) for one endpoint."""
    if url.startswith("sqlite:"):
        path = Path(url.removeprefix("sqlite:///"))
        return ((None, f"{path.name}: the SQLite file is there", {}) if path.is_file()
                else (f"the SQLite file {path.name} is not there", f"{path.name}: not there", {}))
    hp = tg.host_port(url)
    if hp is None:
        return f"{url} names no host", f"{url}: no host", {}
    if url.startswith(("http://", "https://")):
        return _http_health(url, hp[0], quota_min)
    started = time.monotonic()
    try:
        with infra.connect(hp, timeout=5):
            pass
    except OSError as exc:
        return f"{hp[0]}:{hp[1]} does not answer", f"{hp[0]}:{hp[1]}: {type(exc).__name__}", {}
    ms = round((time.monotonic() - started) * 1000)
    return None, f"{hp[0]}:{hp[1]} answers in {ms} ms; quota headroom: not reported", {"ms": ms}


def integration(ctx: Ctx) -> dict[str, Any]:
    if bad := infra_settings.unusable("integration", ctx.config):
        return not_measured(bad)
    found = tg.bindings(ctx.project)
    wanted = tg.as_list(ctx.config.get("integrations"))
    found = [b for b in found if not wanted or b["name"] in wanted]
    if not found:
        return not_measured("no integration to check: the project declares none (declare one in the Plan's Data "
                            "integrations)")
    env, quota_min = str(ctx.config.get("environment") or "") or None, infra.number(ctx, "quota_min_pct", 10)
    dates = _expiries(ctx)
    problems, lines, rows, unbound = [], [], [], []
    for b in found:
        url, where = tg.endpoint_of(b, env)
        cred_problems, cred_lines = _credential_lines(ctx, b["credentials"], dates)
        problems += [f"{b['name']}: {p}" for p in cred_problems]
        if not url:
            unbound.append(b["name"])
            lines += [f"{b['name']}: not bound to an endpoint yet", *cred_lines]
            continue
        problem, line, measured = _endpoint_health(url, quota_min)
        rows.append({"integration": b["name"], "environment": where, **measured})
        lines += [f"{b['name']} ({where}): {line}", *cred_lines]
        if problem:
            problems.append(f"{b['name']}: {problem}")
    if problems:
        return result("failed", "; ".join(problems), lines, integrations=rows, remedy="integration")
    if not rows:
        return not_measured(f"no integration is bound to an endpoint yet ({', '.join(unbound)}): IT binds each on "
                            "a paved road", lines)
    tail = f"; {len(unbound)} not bound yet" if unbound else ""
    return result("passed", f"{len(rows)} integration endpoint(s) answer{tail}", lines, integrations=rows)


# -- scheduled jobs ----------------------------------------------------------------------------------------------

def interval_minutes(trigger: dict[str, Any]) -> int | None:
    from kernel import automations as au

    if trigger.get("every"):
        return au.minutes_of(str(trigger["every"]))
    return 1440 if trigger.get("daily") else 10080 if trigger.get("weekly") else None


def _scheduled_automations(ctx: Ctx) -> list[dict[str, Any]]:
    from kernel import itops_jobs

    return itops_jobs.scheduled(ctx.project)          # active only: a paused one is not late, it was paused


def _stamp(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _automation_lines(ctx: Ctx) -> tuple[list[str], list[str], int]:
    from kernel.automations_run import history

    problems, lines, jobs = [], [], 0
    for a in _scheduled_automations(ctx):
        jobs += 1
        runs = [r for r in history(ctx.project.factory, a["id"], project=ctx.project.pid, limit=50)
                if r.get("kind") == "automation_ran"]
        every = interval_minutes(a["trigger"])
        if not runs:
            lines.append(f"{a['id']} {a.get('name') or ''}: has not run yet (every {every} min)")
            continue
        last = runs[-1]
        at = _stamp(last.get("at"))
        late = at is not None and every and (_now(ctx) - at).total_seconds() > 2 * every * 60
        in_row = 0
        for r in reversed(runs):
            if r.get("outcome") not in ("failed", "refused"):
                break
            in_row += 1
        lines.append(f"{a['id']} {a.get('name') or ''}: last run {last.get('at')} ({last.get('outcome')}); "
                     f"{in_row} failure(s) in a row" + ("; overdue" if late else ""))
        if in_row >= 2:
            problems.append(f"{a['id']} failed {in_row} times in a row")
        if late:
            problems.append(f"{a['id']} missed its schedule (last run {last.get('at')})")
    return problems, lines, jobs


def _duration_lines(ctx: Ctx) -> tuple[list[str], list[str]]:
    from kernel.checks import store as cstore

    rows = [r for r in cstore.results(ctx.project, None, 400) if r.get("via") == "schedule"
            and isinstance(r.get("seconds"), (int, float))]
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(str(r.get("check")), []).append(float(r["seconds"]))
    problems, lines = [], []
    for key, secs in sorted(by.items()):
        if len(secs) < 4:
            lines.append(f"check {key}: {len(secs)} scheduled run(s), too few for a duration trend")
            continue
        recent, earlier = statistics.median(secs[-3:]), statistics.median(secs[:-3])
        lines.append(f"check {key}: median {recent:.1f} s recently, {earlier:.1f} s before")
        if earlier > 0 and recent > earlier * 2 and recent - earlier > 5:
            problems.append(f"check {key} now takes {recent:.0f} s, twice as long as before")
    return problems, lines


def _output_line(ctx: Ctx) -> tuple[list[str], list[str], bool]:
    where = str(ctx.config.get("output") or "").strip()
    if not where:
        return [], ["output freshness: not measured (no output declared: give this check output)"], False
    path, limit = Path(where), infra.number(ctx, "max_age_hours", 26)
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else []
    if not files:
        return [f"the output {path.name} is not there"], [f"output freshness: nothing at {where}"], True
    newest = max(files, key=lambda p: p.stat().st_mtime)
    hours = _age_hours(ctx, newest.stat().st_mtime)
    line = f"output freshness: {newest.name} written {hours:.1f} hours ago (at most {limit})"
    return ([f"the output is {hours:.0f} hours old (over {limit})"] if hours > limit else []), [line], True


def job(ctx: Ctx) -> dict[str, Any]:
    a_problems, a_lines, jobs = _automation_lines(ctx)
    d_problems, d_lines = _duration_lines(ctx)
    o_problems, o_lines, has_output = _output_line(ctx)
    from kernel import itops_jobs

    paused = [f"{a['id']} {a.get('name') or ''}: paused, so not expected to run"
              for a in itops_jobs.paused(ctx.project)]
    lines = a_lines + paused + d_lines + o_lines
    problems = a_problems + d_problems + o_problems
    if problems:
        return result("failed", "; ".join(problems), lines, jobs=jobs, remedy="job")
    if not jobs and not d_lines and not has_output:
        return not_measured("no scheduled work to check: no scheduled automation reaches this project, no check "
                            "runs on a schedule and no output is declared", lines)
    return result("passed", f"{jobs} scheduled automation(s) on time; " + (o_lines[0] if has_output else
                                                                             "no output declared"), lines, jobs=jobs)


CHECKS = (
    Check("database", "Database", "a declared database answers within a budget, its backup is recent and its "
          "storage growth is in bounds", database,
          options=("binding", "endpoint", "environment", "max_ms", "backup_dir", "backup_max_hours", "growth_pct"),
          every="1d"),
    Check("integration", "Integrations", "each declared integration's endpoint answers, its credentials are not "
          "about to expire and its quota has headroom", integration,
          options=("integrations", "environment", "expires", "quota_min_pct"), every="1h"),
    Check("job", "Scheduled jobs", "each scheduled job ran on time, without failures in a row, at its usual "
          "duration, and its output is fresh", job, options=("output", "max_age_hours"), every="6h"),
)
