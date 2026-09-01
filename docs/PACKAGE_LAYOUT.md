# Package Layout

The repository is organized by MVP ownership so each contributor can add code
without mixing domain behavior. Shared compatibility modules remain directly
under `moongcheap_ai` while new domain-specific code belongs in `parts/`.

```text
src/moongcheap_ai/
├── parts/
│   ├── aihub/              # 상품 데이터·Category·Facet·Labeling
│   ├── demand_clustering/  # Consumer Demand grouping and board assignment
│   ├── seller_matching/    # Seller Offer comparison and scoring
│   └── seller_analysis/    # 판매자용 수요 집계와 분석
├── catalog.py              # shared catalog primitives
├── facet.py                # shared facet primitives
└── pipeline.py             # stage orchestration

tests/
└── data_foundation/        # tests grouped by the same ownership boundary
```

Each part should keep its input/output contract local, reuse shared primitives
instead of copying normalization logic, and add tests under the matching
`tests/<part>` directory.
