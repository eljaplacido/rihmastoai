"""The insights in a team's own stack (D-0017): JSON, CSV, or OpenTelemetry-style JSON. Nothing is sent anywhere.

``rihmasto insights export --format json|csv|otlp-json [--out FILE]`` writes a file, or prints when no file is
named. The team sends it on with its own collector or tools; Rihmasto opens no connection.

- **json** is the read models as the cockpit reads them, every dimension or one.
- **csv** is one row per figure: each tile, and each chart's row and series, with its unit, its basis and,
  when it is not measured, why. A figure not measured has an empty value, never 0.
- **otlp-json** follows the OTLP/JSON encoding: ``resourceMetrics`` with one gauge per measured tile
  (``rihmasto.insights.<dimension>.<key>``), and ``resourceSpans`` with one span per model run in the window,
  named and attributed by the OpenTelemetry GenAI semantic conventions (``gen_ai.operation.name``,
  ``gen_ai.request.model``, ``gen_ai.agent.name``, ``gen_ai.usage.input_tokens``,
  ``gen_ai.usage.output_tokens``). A run's record gives the time it was ingested, not its duration, so its
  span starts and ends there. A tile not measured has no data point: OTLP has no way to say "not measured", and
  a zero would say something false.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any

from kernel.insights import gnomon_records as gr
from kernel.insights.base import Scope, stamp, when

FORMATS = ("json", "csv", "otlp-json")
CSV_FIELDS = ("dimension", "scope", "project", "window", "since", "until", "kind", "key", "label", "row", "series",
              "value", "unit", "measured", "why", "basis")
Row = dict[str, Any]


def _models(factory: Any, dimension: str | None, pid: str | None, window: str) -> list[Row]:
    from kernel.insights import overview, read

    if dimension:
        return [read(factory, dimension, pid=pid, window=window)]
    dims: list[Row] = overview(factory, pid=pid, window=window)["dimensions"]
    return dims


def _base(m: Row) -> Row:
    return {"dimension": m["dimension"], "scope": m["scope"], "project": m["project"] or "", "window": m["window"],
            "since": m["since"] or "", "until": m["until"]}


def _chart_rows(m: Row, ch: Row) -> list[Row]:
    out = []
    for r in ch["rows"]:
        values = r.get("values")
        pairs = list(values.items()) if isinstance(values, dict) else [("", r.get("value"))]
        for series, value in pairs:
            out.append(_base(m) | {"kind": "chart", "key": ch["key"], "label": ch["title"],
                                   "row": r.get("at") or r.get("label") or "", "series": series,
                                   "value": "" if value is None else value, "unit": ch["unit"],
                                   "measured": value is not None, "why": r.get("why") or "", "basis": ch["basis"]})
    if not ch["rows"]:
        out.append(_base(m) | {"kind": "chart", "key": ch["key"], "label": ch["title"], "row": "", "series": "",
                               "value": "", "unit": ch["unit"], "measured": False, "why": ch["why"],
                               "basis": ch["basis"]})
    return out


def rows(models: list[Row]) -> list[Row]:
    """One row per figure: each tile, then each chart's rows and series."""
    out = []
    for m in models:
        for t in m["tiles"]:
            out.append(_base(m) | {"kind": "tile", "key": t["key"], "label": t["label"], "row": "", "series": "",
                                   "value": "" if t["value"] is None else t["value"], "unit": t["unit"],
                                   "measured": t["measured"], "why": t["why"] or "", "basis": t["basis"]})
        for ch in m["charts"]:
            out.extend(_chart_rows(m, ch))
    return out


def to_csv(models: list[Row]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows(models))
    return buf.getvalue()


def _nanos(text: str | None) -> str:
    t = when(text)
    return str(int(t.timestamp()) * 1_000_000_000) if t else "0"


def _attr(key: str, value: Any) -> Row:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _attrs(pairs: dict[str, Any]) -> list[Row]:
    return [_attr(k, v) for k, v in pairs.items() if v is not None and v != ""]


def _metric(m: Row, t: Row) -> Row:
    point: Row = {"startTimeUnixNano": _nanos(m["since"]), "timeUnixNano": _nanos(m["until"]),
             "attributes": _attrs({"rihmasto.scope": m["scope"], "rihmasto.project": m["project"],
                                   "rihmasto.window": m["window"]})}
    value = t["value"]
    point |= {"asInt": str(value)} if isinstance(value, int) else {"asDouble": float(value)}
    return {"name": f"rihmasto.insights.{m['dimension']}.{t['key']}", "description": f"{t['label']}: {t['basis']}",
            "unit": {"%": "%", "h": "h", "tokens": "{token}"}.get(t["unit"], t["unit"] or "1"),
            "gauge": {"dataPoints": [point]}}


def _span(r: Row) -> Row:
    seed = f"{r['project']}:{r['run'] or r['at']}"
    at = _nanos(stamp(r["at"]))
    op = "invoke_agent"
    return {"traceId": hashlib.sha256(("trace:" + seed).encode()).hexdigest()[:32],
            "spanId": hashlib.sha256(("span:" + seed).encode()).hexdigest()[:16],
            "name": f"{op} {r['role'] or 'agent'}", "kind": 3, "startTimeUnixNano": at, "endTimeUnixNano": at,
            "attributes": _attrs({"gen_ai.operation.name": op, "gen_ai.agent.name": r["role"],
                                  "gen_ai.request.model": r["model"], "gen_ai.usage.input_tokens": r["in"],
                                  "gen_ai.usage.output_tokens": r["out"], "rihmasto.project": r["project"],
                                  "rihmasto.task": r["task"], "rihmasto.round": r["round"],
                                  "rihmasto.endpoint": r["endpoint"], "rihmasto.runner": r["runner"],
                                  "rihmasto.run": r["run"], "rihmasto.cost": r["cost"],
                                  "rihmasto.cost.currency": r["currency"] if r["cost"] is not None else None}),
            "status": {"code": 1 if r["verdict"] == "passed" else 0}}


def to_otlp(models: list[Row], runs: list[Row]) -> Row:
    resource = {"attributes": _attrs({"service.name": "rihmasto", "telemetry.sdk.name": "rihmasto-insights"})}
    scope = {"name": "rihmasto.insights", "version": "1"}
    metrics = [_metric(m, t) for m in models for t in m["tiles"] if t["measured"]]
    spans = [_span(r) for r in runs]
    return {"resourceMetrics": [{"resource": resource, "scopeMetrics": [{"scope": scope, "metrics": metrics}]}],
            "resourceSpans": [{"resource": resource, "scopeSpans": [{"scope": scope, "spans": spans}]}]}


def export(factory: Any, fmt: str, *, dimension: str | None = None, pid: str | None = None,
           window: str = "7d") -> str:
    """The insights as text in one of FORMATS."""
    if fmt not in FORMATS:
        raise ValueError(f"the format is one of {', '.join(FORMATS)}, got {fmt!r}")
    models = _models(factory, dimension, pid, window)
    if fmt == "csv":
        return to_csv(models)
    if fmt == "json":
        return json.dumps({"source": "rihmasto insights", "dimensions": models}, indent=2, default=str) + "\n"
    runs = gr.runs(Scope(factory, pid=pid, window=window))
    return json.dumps(to_otlp(models, runs), indent=2) + "\n"
