# A Labeling and B Clustering Resource Requirements V1

## Current Deployment Decision

Model execution is mandatory for A. `Rule-first` describes the routing and
validation policy, not a model-free deployment: the model handles the demand
rows that the deterministic parser cannot resolve, and the parser remains the
owner of polarity and `MUST`/`PREFER`/`EXCLUDE` semantics.

The current deployment target is an A labeling CronJob plus a separate model
Worker Pod. The A image does not contain Ollama or model weights; the Worker
endpoint and its resources are supplied by Cloud. A local/in-process model is
only a fallback experiment and is not the current container contract.

## Resource Plan

| Component | Requests | Limits | Notes |
| --- | --- | --- | --- |
| A labeling CronJob | CPU 1 / memory 2Gi | CPU 2 / memory 3Gi | PostgreSQL, taxonomy, external model Worker |
| B clustering, supplied baseline | CPU 1 / memory 3Gi | CPU 2 / memory 4Gi | Includes the current E5 CPU inference path |
| A + B sequential in one CronJob, no local LLM | CPU 2 / memory 5Gi | CPU 4 / memory 8Gi | Recommended combined-job starting point |
| A + B with external LLM API | CPU 2 / memory 5Gi | CPU 4 / memory 8Gi | Adds network timeout/retry requirements, not model memory |

If A and B remain separate CronJobs, reserve their requests independently. The
model Worker resource budget is separate and must be supplied by Cloud after the
Worker image/model and protocol are fixed.

## Local Model Evaluation

Local model results from the 200-row comparison were not good enough to make a model-only production choice. If a local fallback is still required:

- Qwen 2.5 3B Q4: the local Ollama process reported about 2.3GB resident before
  the A Python process is counted; the current 3Gi limit is therefore unsafe.
  Test with CPU 4, memory 4Gi first, then raise to 6Gi if the process is OOM-killed.
- Qwen 3 8B: start at CPU 8, memory 12Gi; limit CPU 8, memory 16Gi. The measured 200-row run used 1,226 seconds and had 79 model failures, so it is not the MVP default.

These local-model values are capacity starting points, not measured Kubernetes guarantees.
If the in-Pod model cannot meet the memory or timeout budget, the fallback is to
request a separate worker; that is an infrastructure contingency, not the default
architecture for A.

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
