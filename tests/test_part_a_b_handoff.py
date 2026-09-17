from __future__ import annotations

import pandas as pd

from scripts.demand.build_part_a_b_clustering_input import build


def test_part_a_b_handoff_separates_evaluation_metadata(tmp_path) -> None:
    raw = pd.DataFrame([{
        "demand_id": "d1",
        "catalog_id": "c1",
        "category_id": "health-functional-food:protein",
        "extra_requirement": "분말 제품을 원해요.",
        "desired_price_min": "1000",
        "desired_price_max": "2000",
        "quantity": "2",
        "is_substitutable": "true",
        "data_origin": "SYNTHETIC_GROUNDED",
        "scenario_type": "SINGLE_FACET",
        "profile_id": "profile-1",
        "expected_facet_profile": "{}",
        "source_evidence_text": "evidence",
    }])
    runtime = pd.DataFrame([{
        "demand_id": "d1",
        "catalog_id": "c1",
        "category_id": "health-functional-food:protein",
        "label": "1-0-0",
        "status": "PARSED",
        "constraints": "[]",
        "reasonCodes": "[]",
        "taxonomyVersion": "v2.2",
        "effectiveRequirementMode": "STRUCTURED",
    }])
    raw_path = tmp_path / "raw.csv"
    runtime_path = tmp_path / "runtime.csv"
    output_path = tmp_path / "b.csv"
    metadata_path = tmp_path / "metadata.csv"
    raw.to_csv(raw_path, index=False)
    runtime.to_csv(runtime_path, index=False)

    result = build(raw_path, runtime_path, output_path, metadata_path)

    assert result == {"rows": 1, "labeled_rows": 1, "review_rows": 0, "conflict_rows": 0}
    handoff = pd.read_csv(output_path, dtype=str)
    metadata = pd.read_csv(metadata_path, dtype=str)
    assert "expected_facet_profile" not in handoff.columns
    assert "expected_facet_profile" in metadata.columns
    assert len(handoff) == len(metadata) == 1
