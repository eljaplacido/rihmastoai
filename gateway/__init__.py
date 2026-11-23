"""The Rihma capability gateway: one OpenAI-compatible endpoint that serves capabilities by workload.

Clients name a workload ("classify", "dev-assistant") in the request's `model` field, never a model,
so the models behind a workload can change without the clients changing. Each workload declares a
fallback ladder (L1 to L4), quotas keep batch work from starving interactive work, and every request
is one record in a content-free, hash-chained audit. See docs/guides/gateway.md (FR-Y1).
"""
