# Package Layout

The repository is organized by MVP ownership so each contributor can add code
without mixing domain behavior. Shared compatibility modules remain directly
under `moongcheap_ai` while new domain-specific code belongs in `parts/`.

```text
src/moongcheap_ai/
├── parts/
│   ├── aihub/              # A-part data foundation and source adapters
│   ├── demand_clustering/  # demand grouping and board assignment
│   ├── seller_matching/    # seller offer comparison and scoring
│   └── seller_analysis/    # seller-facing demand aggregates and explanations
├── catalog.py              # shared catalog primitives
├── facet.py                # shared facet primitives
└── pipeline.py             # stage orchestration

tests/
└── data_foundation/        # tests grouped by the same ownership boundary
```

Each part should keep its input/output contract local, reuse shared primitives
instead of copying normalization logic, and add tests under the matching
`tests/<part>` directory.
