---
id: D-0020
decided_by: owner
decided_on: 2026-11-23
kind: scope
---

# Model capabilities: training, fine-tuning, evaluation and serving are first-class work

The owner (2026-11-23): the factory should support not only apps and systems but "a single, just a model
with a chat feature or maybe some fine tuning", MLOps-style workflows.

**What this means:**
- **Templates and the pipeline.** The ml_pipeline work grows a training template (data preparation,
  training, evaluation, a pinned configuration and seed, a reproducible run record) and a serving template
  (an OpenAI-compatible endpoint over a fine-tuned model, or a plain REST endpoint for a classic model).
  Fine-tuning runs as a pipeline: a base model from the catalogue, datasets pinned by hash with a data
  card and licence and personal-data checks, training on a compute road, and as outputs the weights or
  adapter pinned by digest, a model card and an evaluation report.
- **Evaluations are the gate.** A metric and its threshold on a visible evaluation set; a hidden test set
  in holdout custody that training never sees; regression against the base model and the previous
  version; the red team's safety evaluations; latency and cost probes.
- **Promotion is a person's decision.** A model version moves from candidate to staging to production by a
  person's decision, and can be rolled back in one step.
- **A chat front.** A system prompt, optional retrieval and tools, served through the capability faces
  (website chat, MCP, OpenAI-compatible).
- **The loop closes.** Drift and user feedback come back as proposals (new training data, a retrain) that a
  person approves. Every model version traces from its datasets to its training run, its evaluations, its
  decision and its release.
- **The kernel stays standard-library only.** Training code is part of the product the cells build and
  runs on a road, like delivery.
- **Compute: the GPU box first.** Training runs first on the local GPU box as a compute road. Cloud ML
  platforms come later through Gnomon's integration lanes (D-0015).
- **The live acid test downloads only after naming what it fetches.** It may fetch a small open base model,
  a small permissively licensed public dataset and a pinned training image to the GPU box, but only after
  naming each one with its licence and size.
