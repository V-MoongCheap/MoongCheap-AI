# A Labeling and B Clustering Resource Requirements V1

## Current Deployment Decision

The selected A path is Rule-first Hybrid: deterministic parsing handles clear
requests and the configured Ollama/Qwen 2.5 7B endpoint assists only unresolved,
eligible positive requests. It is not a model-free production design, but the
model is not called for every row. Rule/parser code owns polarity and
`MUST`/`PREFER`/`EXCLUDE` semantics; model output is accepted only after the
taxonomy and source-evidence checks.

Cloud reported on 2026-09-30 that Ollama with `qwen2.5:7b-instruct` is provided
as a separate Cloud-managed service and A calls it over HTTP. Ollama/model
weights are not included in the A image. Cloud owns Ollama scheduling and its
node placement; A CronJob resource requests remain the Python/DB client budget.
This is a Cloud-reported deployment state, not an independent live-cluster
verification from this repository.

## Resource Plan

| Component | Requests | Limits | Notes |
| --- | --- | --- | --- |
| A labeling CronJob baseline | CPU 1 / memory 2Gi | CPU 2 / memory 3Gi | Python, PostgreSQL, taxonomy, remote Ollama HTTP client; model weights/runtime excluded |
| B clustering, supplied baseline | CPU 1 / memory 3Gi | CPU 2 / memory 4Gi | Includes the current E5 CPU inference path |
| A + B sequential in one CronJob with external Ollama | CPU 2 / memory 5Gi | CPU 4 / memory 8Gi | Combined-job estimate; Ollama resources are separate |

If A and B remain separate CronJobs, reserve their requests independently. The
external Ollama workload has its own Cloud-side resource budget and is not
included in A's Pod requests above.

## Local Model Evaluation (historical sizing evidence)

Local model results from the 200-row comparison were not good enough to make a model-only production choice. If a local fallback is still required:

- Qwen 2.5 3B Q4: the local Ollama process reported about 2.3GB resident before
  the A Python process is counted; the current 3Gi limit is therefore unsafe.
  Test with CPU 4, memory 4Gi first, then raise to 6Gi if the process is OOM-killed.
- Qwen 3 8B: start at CPU 8, memory 12Gi; limit CPU 8, memory 16Gi. The measured 200-row run used 1,226 seconds and had 79 model failures, so it is not the MVP default.

These local-model values are historical capacity observations, not measured
Kubernetes guarantees or the current Cloud placement. The current arrangement
uses Cloud-managed Ollama; do not use these figures as A Pod sizing.

An additional `qwen3:4b` Q4_K_M test used about 2.9GB of Ollama resident model
memory and returned all 15 Supported Gold requests, but it produced a non-default
label for only 2 of 10 Gold requests that contained expected constraints. It was
therefore rejected on quality grounds despite being smaller than the 7B model.

## Alias Application Status

The reviewed Alias sheet has 62 accepted-or-corrected rows and 4 rejected rows. The generated apply audit is:

- `data/processed/downstream_v2_1/model1_reviewed_aliases_v1.json`
- `data/processed/downstream_v2_1/model1_alias_apply_audit_v1.csv`
- `config/taxonomy_value_crosswalk_v1.json`

The crosswalk resolves four `product_form` targets (`tablet`, `powder`, `capsule`, `liquid`) to the current Korean taxonomy values. Those four targets are ready in the reviewed Alias registry and were smoke-tested across category-specific code orders. The other 16 targets remain blocked because their Facets are not present in the current V2.1 Taxonomy. The Taxonomy JSON itself remains unchanged.
