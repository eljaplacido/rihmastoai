---
id: D-0005
decided_by: owner
decided_on: 2026-11-22
kind: principle
---

# The factory runs on whatever model families are available

**Decision.** No part of Gnomon Factory depends on a specific model family or vendor:
not the roles, gates, tools, intake, specs or verdicts. Every model is a per-role setting
in the Gnomon surface (`.gnomon/roles.toml` and profiles). It can be swapped to any
endpoint Gnomon supports: local (llama.cpp, Ollama, vLLM), OpenCode Go or Zen, OpenRouter,
or any OpenAI-compatible server. Which model serves which role is settled by benchmarks,
local first, with cloud on capacity or evidence.

**The owner's words:** "we don't have to stick with using Claude. We have open code
endpoints as well … running this factory shouldn't be dependent on the model family we
have available."

**State on 2026-11-22:**
- builder and scout: local `qwen3.6-35b` on the GPU box;
- verifier: `glm-5.3` on OpenCode Go;
- escalation and the `cloud_build` fallback: `deepseek-v4-pro` on OpenCode Go.

No surface, contract or tool names Claude. Solution Factory run B used Claude only as one
comparison arm for the spec, at the owner's earlier choice. Runs on other families are
equally valid inputs.

**How to apply.**
- A model-specific workaround goes in a profile, never in a role's base definition or in
  the kernel.
- Preflight (FR-O8-AC-3) runs on whatever lane is configured.
- A requirement or test that only passes on one family is a defect.
