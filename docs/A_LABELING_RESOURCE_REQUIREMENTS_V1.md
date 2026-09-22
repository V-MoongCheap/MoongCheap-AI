# A Labeling and B Clustering Resource Requirements V1

## Recommended MVP Deployment

Use `Rule-first Hybrid` for the server deployment. The A Pod performs Rule/Alias
labeling, then sends only unresolved or conflicting requests to a separate LLM
Worker. The current A Pod does not contain the model weights or Ollama runtime.

Keep the model outside the A labeling CronJob and B clustering CronJob as a
separate worker. Do not load a local 3B/7B model into the current 3Gi A container.
The selected worker candidate is `qwen2.5:7b-instruct` Q4_K_M; its worker needs a
separate memory budget and is not included in the A Pod budget.

## Resource Plan

| Component | Requests | Limits | Notes |
| --- | --- | --- | --- |
| A Rule-first labeling only | CPU 1 / memory 2Gi | CPU 2 / memory 3Gi | PostgreSQL read, taxonomy, CSV/JSON output |
| B clustering, supplied baseline | CPU 1 / memory 3Gi | CPU 2 / memory 4Gi | Includes the current E5 CPU inference path |
| A + B sequential in one CronJob, no local LLM | CPU 2 / memory 5Gi | CPU 4 / memory 8Gi | Recommended combined-job starting point |
| A + B with external LLM API | CPU 2 / memory 5Gi | CPU 4 / memory 8Gi | Adds network timeout/retry requirements, not model memory |

If A and B remain separate CronJobs, reserve their requests independently: at least 2 CPU and 5Gi memory in total when both can run concurrently. The limits are 4 CPU and 7Gi memory for the two separate jobs, excluding a remote model service.

## Local Model Option (separate worker)

Local model results from the 200-row comparison were not good enough to make a model-only production choice. If a local fallback is still required:

- Qwen 2.5 3B or EXAONE 2.4B quantized: start at CPU 4, memory 8Gi; limit CPU 6, memory 12Gi.
- Qwen 3 8B: start at CPU 8, memory 12Gi; limit CPU 8, memory 16Gi. The measured 200-row run used 1,226 seconds and had 79 model failures, so it is not the MVP default.

These local-model values are capacity starting points, not measured Kubernetes guarantees. The model runtime should be a separate worker or service so a slow/failing LLM cannot block clustering.

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
